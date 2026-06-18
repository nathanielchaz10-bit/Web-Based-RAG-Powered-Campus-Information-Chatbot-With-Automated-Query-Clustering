# database/inspect_db.py
# ─────────────────────────────────────────────────────────────────────────────
# Read-only sanity check: prints row counts (and a few sample rows) for the
# tables the RAG + clustering engines are supposed to populate. Safe to run any
# time, including while the server is running.
#
# Usage (from the hccs_rag_chatbot/ directory, venv active):
#     python database/inspect_db.py

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, engine
from app.models.role import Role
from app.models.user_account import UserAccount
from app.models.chat_session import ChatSession
from app.models.query_log import QueryLog
from app.models.chat_response import ChatResponse
from app.models.clustering_run import ClusteringRun
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.document import Document


def main():
    print("\n" + "=" * 60)
    print("DATABASE POPULATION CHECK")
    print("=" * 60)
    print("DB file:", engine.url.database)
    print("-" * 60)

    db = SessionLocal()
    try:
        counts = [
            ("roles", db.query(Role).count()),
            ("user_accounts", db.query(UserAccount).count()),
            ("chat_sessions", db.query(ChatSession).count()),
            ("query_logs", db.query(QueryLog).count()),
            ("  └ with cached embedding", db.query(QueryLog).filter(QueryLog.query_vector.isnot(None)).count()),
            ("  └ assigned to a cluster", db.query(QueryLog).filter(QueryLog.cluster_id.isnot(None)).count()),
            ("chat_responses", db.query(ChatResponse).count()),
            ("clustering_runs", db.query(ClusteringRun).count()),
            ("clusters", db.query(Cluster).count()),
            ("cluster_keywords", db.query(ClusterKeyword).count()),
            ("documents (not wired yet)", db.query(Document).count()),
        ]
        for name, n in counts:
            print(f"  {name:<32} {n}")

        # --- sample: most recent chat turns ---
        recent = db.query(QueryLog).order_by(QueryLog.query_id.desc()).limit(3).all()
        if recent:
            print("-" * 60)
            print("Most recent queries:")
            for q in reversed(recent):
                ans = q.response.response_text if q.response else "(no response row)"
                print(f"  Q[{q.query_id}] {q.query_text}")
                print(f"        -> {ans[:90]}{'...' if len(ans) > 90 else ''}")
                print(f"        cluster_id={q.cluster_id} response_time_ms={q.response_time_ms}")

        # --- sample: latest clusters ---
        latest_run = db.query(ClusteringRun).order_by(ClusteringRun.run_id.desc()).first()
        if latest_run:
            print("-" * 60)
            print(f"Latest clustering run #{latest_run.run_id} "
                  f"(status={latest_run.status}, clusters={latest_run.num_clusters_found}):")
            clusters = db.query(Cluster).filter_by(clustering_run_id=latest_run.run_id).all()
            for c in clusters:
                kws = [k.keyword for k in c.keywords]
                print(f"  • {c.cluster_label} — {c.query_count} queries ({c.cluster_percentage}%)")
                print(f"      keywords: {', '.join(kws) if kws else '(none)'}")
    finally:
        db.close()

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
