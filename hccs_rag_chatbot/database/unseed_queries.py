"""Remove the sample queries inserted by seed_queries.py.

This is the targeted, non-destructive counterpart to ``seed_queries.py
--reset``. Where ``--reset`` wipes *every* row in query_logs (plus all
clusters/keywords/runs), this script deletes only the rows whose text exactly
matches an entry in seed_queries.SAMPLE_QUERIES, so any real student queries in
the database are left untouched.

Run from inside hccs_rag_chatbot/:
    python database/unseed_queries.py            # dry run: report what would go
    python database/unseed_queries.py --yes      # actually delete the seeded rows

Because the seed list is imported directly from seed_queries.py, the two stay in
sync automatically: add a question to SAMPLE_QUERIES and it becomes removable
here too.

Note on clustering artifacts: deleting seeded queries is FK-safe (query_logs
holds the FKs to clusters / clustering_runs, not the other way around), so the
rows just disappear. Any clusters that were built from them are left in place
but will have fewer (or zero) members. If you also want to clear the clustering
output, pass --clusters to additionally remove cluster_keywords, clusters and
clustering_runs (this clears ALL clustering output, not only seed-derived
clusters, since membership isn't tracked per-source).
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
import app.models  # noqa: F401  registers all ORM models on Base.metadata
from app.models.query_log import QueryLog

from database.seed_queries import SAMPLE_QUERIES


def _seeded_texts():
    """Flatten SAMPLE_QUERIES into the set of exact query strings the seeder adds."""
    return {q for qs in SAMPLE_QUERIES.values() for q in qs}


def unseed(confirm: bool = False, clusters: bool = False):
    db = SessionLocal()
    try:
        texts = _seeded_texts()

        # Count first so a dry run can report without touching anything.
        present = (
            db.query(QueryLog)
            .filter(QueryLog.query_text.in_(texts))
            .count()
        )

        if not confirm:
            print(f"Dry run: {present} of {len(texts)} seeded queries are present "
                  f"and would be deleted.")
            if clusters:
                print("Would also clear ALL cluster_keywords, clusters and "
                      "clustering_runs (--clusters).")
            print("Re-run with --yes to actually delete.")
            return

        if clusters:
            # Children first so FK constraints are satisfied.
            from app.models.cluster_keyword import ClusterKeyword
            from app.models.cluster import Cluster
            from app.models.clustering_run import ClusteringRun

            kw = db.query(ClusterKeyword).delete()
            cl = db.query(Cluster).delete()
            runs = db.query(ClusteringRun).delete()
            print(f"Cleared clustering output: {cl} clusters, {kw} keywords, "
                  f"{runs} runs.")

        deleted = (
            db.query(QueryLog)
            .filter(QueryLog.query_text.in_(texts))
            .delete(synchronize_session=False)
        )
        db.commit()

        remaining = db.query(QueryLog).count()
        print(f"Removed {deleted} seeded queries. "
              f"Queries remaining in DB: {remaining}.")
    except Exception as exc:
        db.rollback()
        print(f"Unseed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    unseed(
        confirm="--yes" in sys.argv,
        clusters="--clusters" in sys.argv,
    )
