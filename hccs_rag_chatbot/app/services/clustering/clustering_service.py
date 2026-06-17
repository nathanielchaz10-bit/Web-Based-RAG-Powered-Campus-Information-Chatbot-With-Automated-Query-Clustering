"""Clustering service: runs the original LLM-clustering engine against the
relational schema (QueryLog / Cluster / ClusterKeyword / ClusteringRun).

It reuses the heavy lifting from src/cluster_engine.py (embedding-based
deduplication + LLM topic grouping) so the algorithm stays in one place, and
only the persistence layer is re-pointed from the flat analytics.db to the
SQLAlchemy models in hccs_rag.db.
"""

import json
import re
import time
from collections import Counter
from datetime import datetime

import app.services._engine_bootstrap  # noqa: F401  (sys.path + GOOGLE_API_KEY)

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.query_log import QueryLog
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.clustering_run import ClusteringRun

# Very small English/Taglish stopword set — enough to keep extracted keywords
# meaningful without pulling in an NLP dependency.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "and", "or",
    "do", "i", "how", "what", "when", "where", "can", "my", "me", "you", "we",
    "does", "did", "with", "be", "this", "that", "it", "if", "at", "as", "by",
    "from", "about", "get", "there", "have", "has", "was", "will", "would",
    "should", "po", "ba", "ng", "sa", "ang", "mga", "na", "ko", "ang", "yung",
}


def _extract_keywords(texts: list[str], top_n: int = 4) -> list[tuple[str, int]]:
    """Return up to top_n (keyword, frequency) pairs across the given queries."""
    counter: Counter = Counter()
    for text in texts:
        for tok in re.findall(r"[a-zA-Z]{3,}", text.lower()):
            if tok not in _STOPWORDS:
                counter[tok] += 1
    return counter.most_common(top_n)


def _embed_missing(db: Session) -> None:
    """Embed any QueryLog rows that don't have a cached query_vector yet.

    Mirrors src.cluster_engine._embed_missing_queries but writes to
    QueryLog.query_vector (Text holding JSON) instead of the old analytics.db.
    """
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    rows = (
        db.query(QueryLog)
        .filter(QueryLog.query_vector.is_(None))
        .all()
    )
    if not rows:
        return

    print(f"[clustering] Embedding {len(rows)} new queries...")
    model = GoogleGenerativeAIEmbeddings(
        model=settings.EMBEDDING_MODEL, task_type="CLUSTERING"
    )

    batch_size = 90
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        vectors = model.embed_documents([r.query_text for r in batch])
        for row, vec in zip(batch, vectors):
            row.query_vector = json.dumps(vec)
        db.commit()
        if i + batch_size < len(rows):
            print("[clustering] Approaching API limit. Sleeping 60s.")
            time.sleep(60)


def run_clustering(db: Session, triggered_by_user_id: int | None = None) -> dict:
    """Cluster all valid query logs and persist the result as a ClusteringRun.

    Returns a small summary dict: run_id, total_queries, num_clusters.
    """
    import numpy as np
    from sklearn.preprocessing import normalize
    from langchain_google_genai import ChatGoogleGenerativeAI
    from src.cluster_engine import _deduplicate, _llm_cluster

    min_size = settings.CLUSTERING_MIN_QUERIES

    run = ClusteringRun(
        run_timestamp=datetime.utcnow(),
        status="RUNNING",
        triggered_by_user_id=triggered_by_user_id,
        parameters=json.dumps({
            "min_cluster_size": min_size,
            "embedding_model": settings.EMBEDDING_MODEL,
            "llm_model": settings.LLM_MODEL,
        }),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        # 1. Ensure every query has a cached embedding (used for dedup only).
        _embed_missing(db)

        # 2. Load all valid, embedded queries.
        rows = (
            db.query(QueryLog)
            .filter(QueryLog.is_valid.is_(True))
            .filter(QueryLog.query_vector.isnot(None))
            .all()
        )

        if len(rows) < min_size:
            run.status = "COMPLETED"
            run.total_queries = len(rows)
            run.num_clusters_found = 0
            run.completed_at = datetime.utcnow()
            db.commit()
            return {"run_id": run.run_id, "total_queries": len(rows),
                    "num_clusters": 0, "message": f"Need at least {min_size} queries."}

        ids = [r.query_id for r in rows]
        texts = [r.query_text for r in rows]
        by_id = {r.query_id: r for r in rows}
        vectors = np.array([json.loads(r.query_vector) for r in rows])
        normed = normalize(vectors)

        # 3. Collapse near-duplicates; each group's first member represents it.
        dup_groups = _deduplicate(normed)
        rep_texts = [texts[g[0]] for g in dup_groups]

        # 4. LLM groups the representatives into named topics.
        llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
        llm_groups = _llm_cluster(llm, rep_texts)
        if not llm_groups:
            run.status = "FAILED"
            run.total_queries = len(rows)
            run.completed_at = datetime.utcnow()
            db.commit()
            return {"run_id": run.run_id, "total_queries": len(rows),
                    "num_clusters": 0, "message": "LLM produced no grouping."}

        total = len(rows)
        clusters_created = 0

        for group in llm_groups:
            name = str(group.get("name", "")).strip() or "Unnamed Cluster"
            members = group.get("members", [])

            # Expand each representative back to all its near-duplicate originals.
            member_query_ids: list[int] = []
            for rep_pos in members:
                if not isinstance(rep_pos, int) or not (0 <= rep_pos < len(dup_groups)):
                    continue
                for original_idx in dup_groups[rep_pos]:
                    member_query_ids.append(ids[original_idx])

            if len(member_query_ids) < min_size:
                continue  # leave tiny topics unclustered (noise)

            member_texts = [by_id[qid].query_text for qid in member_query_ids]
            cluster = Cluster(
                cluster_label=name,
                cluster_description=(
                    f"Automatically generated cluster containing "
                    f"{len(member_query_ids)} queries."
                ),
                query_count=len(member_query_ids),
                cluster_percentage=round(100.0 * len(member_query_ids) / total, 2),
                cluster_status="ACTIVE",
                clustering_run_id=run.run_id,
            )
            db.add(cluster)
            db.flush()  # assign cluster_id

            for keyword, freq in _extract_keywords(member_texts):
                db.add(ClusterKeyword(
                    cluster_id=cluster.cluster_id,
                    keyword=keyword,
                    frequency=freq,
                    relevance_score=round(freq / len(member_query_ids), 3),
                ))

            for qid in member_query_ids:
                row = by_id[qid]
                row.cluster_id = cluster.cluster_id
                row.clustering_run_id = run.run_id

            clusters_created += 1

        run.status = "COMPLETED"
        run.total_queries = total
        run.num_clusters_found = clusters_created
        run.completed_at = datetime.utcnow()
        db.commit()

        return {"run_id": run.run_id, "total_queries": total,
                "num_clusters": clusters_created}

    except Exception as exc:
        db.rollback()
        run.status = "FAILED"
        run.completed_at = datetime.utcnow()
        db.commit()
        raise exc
