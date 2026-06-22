"""Admin-editable runtime settings, backed by the ``app_settings`` table.

This is the persistence layer behind the Portal Settings page. Each adjustable
parameter is declared once in ``_SPECS`` with its type, bounds, and default;
that single registry drives validation (PUT), defaulting (GET), and startup
loading, so adding a new editable setting is a one-line change.

Two kinds of settings:

  * **Live** (``live=True``): mirrors a field on the global ``settings`` object.
    On startup any persisted override is applied onto ``settings``; on PUT the
    new value is both persisted and written back to ``settings`` so it takes
    effect immediately with no restart. The chat rate limit is the only live
    setting today — the limiter reads ``settings.RATE_LIMIT_MAX_REQUESTS`` on
    every request, so an admin edit applies to the very next query.

  * **Store-only** (``live=False``): persisted and shown in the UI, but not yet
    wired into a running subsystem. The AI sliders (temperature, relevance,
    max tokens) are store-only for now — the RAG engine still uses its built-in
    values — so we deliberately do NOT push them onto ``settings`` and risk a
    half-applied/units-mismatched config. Wiring them to the engine is a
    separate task; when that happens, flip ``live`` and apply with correct units.

Values are stored as strings and cast on read against the spec, so the table
schema never changes as parameters come and go. Overrides are sparse: a row
exists only once an admin saves a value different from the built-in default.
"""

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_setting import AppSetting


@dataclass(frozen=True)
class SettingSpec:
    key: str                       # public name used in the API/JSON + UI
    caster: Callable[[Any], Any]   # str / int / float
    default: Any                   # shown when no override exists (non-live keys)
    attr: str | None = None        # mirrored field on `settings` (live keys)
    live: bool = False             # apply onto `settings` (effective immediately)
    minimum: float | None = None
    maximum: float | None = None
    max_len: int | None = None

    def coerce(self, raw: Any) -> Any:
        """Cast + validate a raw value, raising ValueError on bad input."""
        try:
            val = self.caster(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{self.key}: expected {self.caster.__name__}")
        if isinstance(val, str):
            val = val.strip()
            if not val:
                raise ValueError(f"{self.key}: must not be empty")
            if self.max_len and len(val) > self.max_len:
                raise ValueError(f"{self.key}: too long (max {self.max_len} chars)")
        else:
            if self.minimum is not None and val < self.minimum:
                raise ValueError(f"{self.key}: must be >= {self.minimum}")
            if self.maximum is not None and val > self.maximum:
                raise ValueError(f"{self.key}: must be <= {self.maximum}")
        return val


# The single source of truth for which settings the Portal exposes.
_SPECS: dict[str, SettingSpec] = {
    s.key: s
    for s in [
        # --- General Institution Profile (store-only) ---
        SettingSpec("school_name", str, "Holy Child Catholic School", max_len=120),
        SettingSpec("contact_email", str, "admin@hccs.edu", max_len=120),
        # --- AI Configuration & RAG Intelligence (store-only for now) ---
        SettingSpec("rag_temperature", float, 0.4, minimum=0.0, maximum=1.0),
        SettingSpec("max_context_tokens", int, 4096, minimum=512, maximum=16384),
        SettingSpec("search_relevance_threshold", int, 85, minimum=0, maximum=100),
        # --- Rate limit threshold (LIVE: read by the chat limiter every request) ---
        SettingSpec(
            "rate_limit_max_requests",
            int,
            settings.RATE_LIMIT_MAX_REQUESTS,
            attr="RATE_LIMIT_MAX_REQUESTS",
            live=True,
            minimum=1,
            maximum=1000,
        ),
    ]
}


def _all_overrides(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.query(AppSetting).all()}


def get_effective_settings(db: Session) -> dict[str, Any]:
    """Current value of every exposed setting: live keys read from ``settings``
    (which already reflects any persisted override), others from the stored
    override or the built-in default."""
    overrides = _all_overrides(db)
    out: dict[str, Any] = {}
    for key, spec in _SPECS.items():
        if spec.live and spec.attr:
            out[key] = getattr(settings, spec.attr)
        elif key in overrides:
            try:
                out[key] = spec.coerce(overrides[key])
            except ValueError:
                out[key] = spec.default  # corrupt stored value -> fall back
        else:
            out[key] = spec.default
    return out


def update_settings(db: Session, updates: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist, and (for live keys) apply a batch of setting changes.

    Validation is all-or-nothing: if any value is invalid, ValueError is raised
    and nothing is written. Unknown keys are ignored.
    """
    cleaned: dict[str, Any] = {}
    for key, raw in (updates or {}).items():
        spec = _SPECS.get(key)
        if spec is None:
            continue  # ignore keys we don't expose
        cleaned[key] = spec.coerce(raw)

    for key, val in cleaned.items():
        spec = _SPECS[key]
        row = db.query(AppSetting).filter_by(key=key).first()
        if row is None:
            db.add(AppSetting(key=key, value=str(val)))
        else:
            row.value = str(val)
        if spec.live and spec.attr:
            setattr(settings, spec.attr, val)

    db.commit()
    return get_effective_settings(db)


def load_overrides_into_config(db: Session) -> None:
    """On startup, apply persisted overrides for LIVE settings onto ``settings``
    so admin changes survive a restart. A corrupt stored value is skipped,
    leaving the built-in default in place."""
    overrides = _all_overrides(db)
    for key, spec in _SPECS.items():
        if spec.live and spec.attr and key in overrides:
            try:
                setattr(settings, spec.attr, spec.coerce(overrides[key]))
            except ValueError:
                pass
