"""In-memory sliding-window rate limiters for the student chat path.

Two layers guard the chatbot, because a single student "send" fans out into
several Gemini calls inside the RAG-Fusion pipeline (~2 Flash + 4 embedding
calls per turn). Counting only student sends would under-protect the external
Gemini API:

  * Per-user limiter (the "front door"): caps how many queries one authenticated
    user may submit per window. This is the abuse / DDoS guard the paper
    describes -- it stops one person scripting the send button.

  * Global limiter (the "back door"): caps how many chat turns the whole server
    admits per window, across all users combined. Because the per-turn Gemini
    fan-out is fixed, a ceiling on admitted turns is equivalently a ceiling on
    calls to Google, so this is what actually keeps the shared Gemini quota from
    being flooded when many users arrive at once. Size it from your quota:
    roughly  global_max ~= (Gemini Flash requests-per-minute) / 2.

Both limiters are process-local (matching the "tracked in server memory"
design): they reset on restart and are not shared across multiple uvicorn
workers. The per-user counter is keyed by ``user_id`` (a session token resolves
to one user; tokens can be re-minted and DEV_MODE has none), the global counter
by a single shared key.

Thresholds are read from ``settings`` on every call, so editing .env and
restarting is enough to retune. A non-positive max (or window) disables that
layer entirely.

Admission is two-phase: ``allow()`` peeks without spending, ``record()`` spends.
The chat dependency checks BOTH limiters with ``allow()`` first and only calls
``record()`` once a request clears both, so a request rejected by one layer
never burns budget in the other.
"""

import math
import threading
import time
from collections import defaultdict, deque

from app.core.config import settings


class SlidingWindowRateLimiter:
    """Fixed-budget sliding window keyed by an arbitrary hashable id.

    The active budget is read live from ``settings`` via the attribute names
    passed at construction, so the same class backs both the per-user and the
    global limiter while staying configurable at runtime.
    """

    def __init__(self, max_attr: str, window_attr: str) -> None:
        # key -> monotonic timestamps of the requests still inside the window.
        self._hits: dict[object, deque[float]] = defaultdict(deque)
        # chat endpoints run in FastAPI's threadpool (sync handlers), so guard
        # the shared dict against concurrent access.
        self._lock = threading.Lock()
        self._max_attr = max_attr
        self._window_attr = window_attr

    def _limits(self) -> tuple[int, int]:
        return getattr(settings, self._max_attr), getattr(settings, self._window_attr)

    def allow(self, key: object) -> tuple[bool, int]:
        """Peek whether ``key`` may proceed, WITHOUT spending a slot.

        Returns ``(allowed, retry_after_seconds)``. When not allowed,
        ``retry_after`` is the whole number of seconds until the oldest in-window
        hit ages out (a slot frees up). Prunes expired hits as a side effect.
        """
        max_requests, window = self._limits()
        # A non-positive limit (or window) disables this layer entirely.
        if max_requests <= 0 or window <= 0:
            return True, 0

        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= max_requests:
                # Oldest hit leaves the window at hits[0] + window.
                return False, max(1, math.ceil(hits[0] + window - now))
            return True, 0

    def record(self, key: object) -> None:
        """Spend one slot for ``key``. Call only after deciding to admit."""
        max_requests, window = self._limits()
        if max_requests <= 0 or window <= 0:
            return
        with self._lock:
            self._hits[key].append(time.monotonic())

    def usage(self, key: object) -> tuple[int, int, int]:
        """Report current window usage for ``key`` WITHOUT spending a slot.

        Returns ``(used, max_requests, window_seconds)`` after pruning expired
        hits, so callers (e.g. the dashboard health panel) can show how much of
        the budget is spent. A non-positive ``max_requests`` means this layer is
        disabled.
        """
        max_requests, window = self._limits()
        if max_requests <= 0 or window <= 0:
            return 0, max_requests, window
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            return len(hits), max_requests, window


# Per-user "front door": abuse / DDoS guard keyed by user_id.
rate_limiter = SlidingWindowRateLimiter(
    "RATE_LIMIT_MAX_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS"
)

# Global "back door": one shared budget protecting the Gemini quota across all
# users. Keyed by a single constant since the budget is server-wide.
global_rate_limiter = SlidingWindowRateLimiter(
    "RATE_LIMIT_GLOBAL_MAX_REQUESTS", "RATE_LIMIT_GLOBAL_WINDOW_SECONDS"
)
GLOBAL_KEY = "__chat_global__"
