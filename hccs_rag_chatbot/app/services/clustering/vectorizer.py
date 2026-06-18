# app/services/clustering/vectorizer.py
"""
Embeds QueryLog text into vectors for clustering.
"""
import json
import time
from typing import List, Tuple

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings

# Same transient-error retry pattern as app/services/rag (kept identical on
# purpose -- if/when this is consolidated into a shared embedder, the retry
# logic is already proven safe).
_TRANSIENT_MARKERS = (
    "500", "internal",
    "503", "unavailable",
    "429", "resource_exhausted", "rate limit", "quota",
    "deadline", "timeout", "timed out",
)


def _is_transient_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def _log_retry(retry_state):
    exc = retry_state.outcome.exception()
    print(f"[clustering embed retry] attempt {retry_state.attempt_number} failed: {exc!r} — retrying...")


_embedding_retry = retry(
    retry=retry_if_exception(_is_transient_error),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    stop=stop_after_attempt(4),
    before_sleep=_log_retry,
    reraise=True,
)


class _RetryingEmbeddings(GoogleGenerativeAIEmbeddings):
    """GoogleGenerativeAIEmbeddings with automatic retry on transient errors."""

    @_embedding_retry
    def embed_documents(self, texts, *args, **kwargs):
        return super().embed_documents(texts, *args, **kwargs)


# Gemini batches embedding requests; keep batches well under any provider-side
# request limits so a single failure doesn't waste a huge amount of work.
_BATCH_SIZE = 90

# Seconds to pause between batches so we don't trip rate limits on large
# backlogs (e.g. first-ever clustering run on a school with months of history).
_BATCH_COOLDOWN_SECONDS = 60


def embed_queries(query_ids: List[int], query_texts: List[str]) -> List[Tuple[int, List[float]]]:
    """
    Embeds a list of query texts in batches.

    Args:
        query_ids: QueryLog.query_id values, same order/length as query_texts.
        query_texts: Raw query text to embed.

    Returns:
        List of (query_id, vector) tuples, in the same order as the input.

    Raises:
        Whatever the underlying API raises after retries are exhausted —
        callers (preprocessor/pipeline) are expected to catch this and log
        an ML failure via ClusteringRun.status, per the SOP2 flowchart's
        "ML Execution Successful? NO -> Log ML Error" branch.
    """
    if not query_ids:
        return []

    model = GoogleGenerativeAIEmbeddings.__new__(_RetryingEmbeddings)
    _RetryingEmbeddings.__init__(
        model,
        model=settings.EMBEDDING_MODEL,
        task_type="CLUSTERING",
    )

    results: List[Tuple[int, List[float]]] = []
    total = len(query_texts)

    for start in range(0, total, _BATCH_SIZE):
        batch_ids = query_ids[start:start + _BATCH_SIZE]
        batch_texts = query_texts[start:start + _BATCH_SIZE]

        print(f"[clustering] Embedding batch {start}-{start + len(batch_texts)} of {total}.")
        batch_vectors = model.embed_documents(batch_texts)

        results.extend(zip(batch_ids, batch_vectors))

        # Only sleep between batches, never after the last one.
        if start + _BATCH_SIZE < total:
            print(f"[clustering] Cooling down {_BATCH_COOLDOWN_SECONDS}s before next batch.")
            time.sleep(_BATCH_COOLDOWN_SECONDS)

    return results


def serialize_vector(vector: List[float]) -> str:
    """QueryLog.query_vector is a Text column — store embeddings as JSON."""
    return json.dumps(vector)


def deserialize_vector(raw: str) -> List[float]:
    return json.loads(raw)