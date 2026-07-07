"""Lightweight, idempotent schema migrations applied on startup.

Why this exists
---------------
The app boots with ``Base.metadata.create_all`` (see ``main.py`` and
``database/__init__db.py``) so a fresh database is usable with zero manual
setup. But ``create_all`` only ever CREATES missing tables -- it never ALTERs
tables that already exist. So when a model gains a new column, existing
databases silently fall out of sync and break at query time.

This module fills that gap. Each migration is a tiny, idempotent step
(check-then-change) and the whole set is run right after ``create_all``. The
result: existing databases self-upgrade on boot, matching the project's
"no manual setup" design. Re-running is always safe -- applied migrations
no-op.

Adding a migration
------------------
When a model change can't be handled by ``create_all`` (a new column, an
index, a backfill, ...), write a function that takes a live Connection,
makes the change only if it isn't already present, and returns True if it
actually changed something. Then append it to ``_MIGRATIONS``. Keep them in
order; never edit or delete a shipped migration (add a new one instead).
"""

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine


def _has_column(conn: Connection, table: str, column: str) -> bool:
    """True if ``table`` already has ``column`` (driver-agnostic check)."""
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def _add_resolved_query_text(conn: Connection) -> bool:
    """query_logs.resolved_query_text: stores the history-aware chain's
    standalone rewrite of a follow-up question, used by query clustering."""
    if _has_column(conn, "query_logs", "resolved_query_text"):
        return False
    conn.exec_driver_sql(
        "ALTER TABLE query_logs ADD COLUMN resolved_query_text TEXT"
    )
    return True


def _add_document_extraction_fields(conn: Connection) -> bool:
    """documents.extraction_method / extraction_confidence / needs_review:
    the ingestion verdict recorded for each uploaded document."""
    changed = False
    columns = [
        ("extraction_method", "ALTER TABLE documents ADD COLUMN extraction_method VARCHAR(50)"),
        ("extraction_confidence", "ALTER TABLE documents ADD COLUMN extraction_confidence VARCHAR(20)"),
        ("needs_review", "ALTER TABLE documents ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT 0"),
    ]
    for name, ddl in columns:
        if not _has_column(conn, "documents", name):
            conn.exec_driver_sql(ddl)
            changed = True
    return changed


def _add_chat_response_is_fallback(conn: Connection) -> bool:
    """chat_responses.is_fallback: whether the assistant declined to answer
    (NO_ANSWER sentinel / refusal), recorded at generation time so the
    dashboard's AI Success Rate is exact rather than guessed from output text."""
    if _has_column(conn, "chat_responses", "is_fallback"):
        return False
    conn.exec_driver_sql(
        "ALTER TABLE chat_responses ADD COLUMN is_fallback BOOLEAN"
    )
    return True


def _add_user_picture_url(conn: Connection) -> bool:
    """user_accounts.picture_url: the Google profile photo URL, shown as the chat
    avatar (falls back to an initial when null)."""
    if _has_column(conn, "user_accounts", "picture_url"):
        return False
    conn.exec_driver_sql(
        "ALTER TABLE user_accounts ADD COLUMN picture_url VARCHAR(512)"
    )
    return True


def _add_query_logs_is_guest(conn: Connection) -> bool:
    """query_logs.is_guest: marks turns from the anonymous guest endpoint so the
    dashboard can distinguish guest inquiries from student ones."""
    if _has_column(conn, "query_logs", "is_guest"):
        return False
    conn.exec_driver_sql(
        "ALTER TABLE query_logs ADD COLUMN is_guest BOOLEAN NOT NULL DEFAULT 0"
    )
    return True


# Ordered list of (description, migration_fn). Append new ones; never mutate
# or remove existing entries.
_MIGRATIONS = [
    ("add query_logs.resolved_query_text", _add_resolved_query_text),
    ("add documents extraction fields", _add_document_extraction_fields),
    ("add chat_responses.is_fallback", _add_chat_response_is_fallback),
    ("add user_accounts.picture_url", _add_user_picture_url),
    ("add query_logs.is_guest", _add_query_logs_is_guest),
]


def run_migrations(engine: Engine) -> None:
    """Apply every pending migration against ``engine``.

    Idempotent and safe to call on every startup: each step checks whether it
    is already applied and no-ops if so. Runs inside a single transaction so a
    failure leaves the schema untouched.
    """
    with engine.begin() as conn:
        for description, migration in _MIGRATIONS:
            if migration(conn):
                print(f"[migrations] applied: {description}")
