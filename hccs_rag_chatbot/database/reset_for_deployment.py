"""Reset the database to a clean 'fresh deployment' state for the eval launch.

Wipes all user-generated / test data (chats, queries, clusters, auth logs,
document-usage analytics) and every account EXCEPT the kept Head Admin, so real
user activity is recorded from zero.

KEEPS (untouched): roles, portal settings (app_settings), and the document
knowledge base — documents + document_chunks + the Chroma vector store — so the
chatbot still answers questions on launch.

Guard: refuses to run unless the kept admin exists as an ACTIVE Head Admin, so a
typo can't wipe the DB and leave nobody able to administer it.

    python database/reset_for_deployment.py          # dry run: report only
    python database/reset_for_deployment.py --yes     # execute the wipe
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.database import SessionLocal
import app.models  # noqa: F401  register all ORM models
from app.models.role import Role
from app.models.user_account import UserAccount

KEEP_ADMIN_EMAIL = "nathanielchaz10@gmail.com"

# Child-before-parent so the deletes satisfy FK order regardless of whether
# SQLite FK enforcement is on. These are ALL user-generated / test data.
WIPE_TABLES = [
    "cluster_keywords",
    "chat_responses",
    "query_logs",
    "clusters",
    "clustering_runs",
    "chat_sessions",
    "document_retrievals",
    "authentication_logs",
    "system_metrics",
]


def reset(confirm: bool = False):
    db = SessionLocal()
    try:
        keep = (
            db.query(UserAccount)
            .join(Role)
            .filter(
                UserAccount.email == KEEP_ADMIN_EMAIL,
                Role.role_name == "Head Admin",
                UserAccount.is_active.is_(True),
            )
            .first()
        )
        if not keep:
            print(f"Refusing to run: {KEEP_ADMIN_EMAIL} is not an active Head Admin "
                  f"in this database. Aborting so nothing is wiped.")
            return

        print(f"Keeping admin: {keep.email} (id={keep.user_id})\n")
        print("WILL WIPE:")
        for t in WIPE_TABLES:
            n = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t:22} {n}")
        others = db.query(UserAccount).filter(UserAccount.email != KEEP_ADMIN_EMAIL).count()
        print(f"  {'user_accounts (test)':22} {others}")

        docs = db.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        chunks = db.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
        appset = db.execute(text("SELECT COUNT(*) FROM app_settings")).scalar()
        roles = db.query(Role).count()
        print("\nWILL KEEP:")
        print(f"  documents={docs}, document_chunks={chunks}, app_settings={appset}, "
              f"roles={roles}, user_accounts(admin)=1, Chroma store (untouched)")

        if not confirm:
            print("\nDry run. Re-run with --yes to execute.")
            return

        for t in WIPE_TABLES:
            db.execute(text(f"DELETE FROM {t}"))
        db.query(UserAccount).filter(
            UserAccount.email != KEEP_ADMIN_EMAIL
        ).delete(synchronize_session=False)
        db.commit()

        print("\nDone. Database reset to fresh-deployment state.")
        print(f"Remaining accounts: {db.query(UserAccount).count()} "
              f"(should be 1: {KEEP_ADMIN_EMAIL})")
    except Exception as exc:
        db.rollback()
        print(f"Reset failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset(confirm="--yes" in sys.argv)
