# app/services/clustering/preprocessor.py

from dataclasses import dataclass
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.query_log import QueryLog


class InsufficientQueriesError(Exception):
    """Raised when fewer than CLUSTERING_MIN_QUERIES are available.

    Caller (pipeline.py) catches this to set ClusteringRun.status =
    'INSUFFICIENT', matching the flowchart's "Update Run Status: Insufficient"
    terminal node.
    """
    def __init__(self, found: int, required: int):
        self.found = found
        self.required = required
        super().__init__(f"Found {found} queries; need at least {required} to cluster.")


class QueryFetchError(Exception):
    """Raised on any DB-level failure fetching queries.

    Caller catches this to set ClusteringRun.status = 'FAILED_EXTRACTION',
    matching the flowchart's "Log Extraction Error" -> "Update Run Status:
    Failed Extraction" branch.
    """
    pass


@dataclass
class QueryRecord:
    query_id: int
    query_text: str


def fetch_clusterable_queries(db: Session) -> List[QueryRecord]:
    """
    Fetches all valid QueryLog rows eligible for clustering.

    Excludes is_valid = False rows (e.g. empty/rate-limited/error queries
    that were logged but never represent a real student question) so they
    don't pollute cluster topics.

    Raises:
        QueryFetchError: if the database read itself fails.
        InsufficientQueriesError: if fewer than settings.CLUSTERING_MIN_QUERIES
            valid queries are found.
    """
    # Cluster on the resolved (standalone) question when one was stored -- it's
    # the context-free rewrite of a follow-up and groups far better than the
    # raw fragment. Falls back to query_text for first-turn / un-rewritten rows.
    clustering_text = func.coalesce(
        QueryLog.resolved_query_text, QueryLog.query_text
    ).label("query_text")

    try:
        rows = (
            db.execute(
                select(QueryLog.query_id, clustering_text)
                .where(QueryLog.is_valid.is_(True))
                .where(QueryLog.query_text.isnot(None))
            )
            .all()
        )
    except Exception as exc:
        raise QueryFetchError(str(exc)) from exc

    records = [QueryRecord(query_id=r.query_id, query_text=r.query_text) for r in rows if r.query_text.strip()]

    if len(records) < settings.CLUSTERING_MIN_QUERIES:
        raise InsufficientQueriesError(found=len(records), required=settings.CLUSTERING_MIN_QUERIES)

    return records