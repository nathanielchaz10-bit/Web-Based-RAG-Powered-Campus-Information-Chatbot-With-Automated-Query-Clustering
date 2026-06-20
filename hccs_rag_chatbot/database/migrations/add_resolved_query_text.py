# database/migrations/add_resolved_query_text.py
#
# Adds query_logs.resolved_query_text to an EXISTING database.
#
# Background: the project has no migration framework -- fresh databases get the
# column automatically from Base.metadata.create_all (__init__db.py), but
# create_all never ALTERs tables that already exist. Run this once against any
# pre-existing hccs_rag.db so its schema matches the QueryLog model.
#
# Idempotent: safe to run multiple times (no-op if the column already exists).
#
# Usage:
#   python database/migrations/add_resolved_query_text.py

import os
import sqlite3
import sys

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(_APP_ROOT)


def _default_db_path() -> str:
    """Resolve the DB path from app config, falling back to the conventional
    location if the app's settings deps aren't installed (this script only
    needs sqlite3 to run)."""
    try:
        from app.core.config import settings
        return settings.SQLITE_DB_PATH
    except Exception:
        return os.path.join(_APP_ROOT, "database", "hccs_rag.db")


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def migrate(db_path: str | None = None) -> None:
    db_path = db_path or _default_db_path()
    if not os.path.exists(db_path):
        print(f"No database at {db_path}; nothing to migrate "
              "(a fresh DB will get the column from create_all).")
        return

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        if _column_exists(cur, "query_logs", "resolved_query_text"):
            print("query_logs.resolved_query_text already present; nothing to do.")
            return
        cur.execute("ALTER TABLE query_logs ADD COLUMN resolved_query_text TEXT")
        con.commit()
        print(f"Added query_logs.resolved_query_text to {db_path}.")
    finally:
        con.close()


if __name__ == "__main__":
    migrate()
