# app/services/clustering/scheduler.py
"""
Triggers the clustering pipeline on a schedule, matching the "Scheduler"
actor in the system architecture diagram and "Clustering Scheduled" in the
SOP2 flowchart. Also exposes trigger_clustering_manually() for the admin
"run clustering now" button referenced in clusters.html / clusters.js.

Uses APScheduler's BackgroundScheduler so it runs inside the same FastAPI
process (no separate worker/cron process needed) -- appropriate for the
school's single-server deployment shown in the architecture diagram.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.clustering.pipeline import run_clustering_pipeline

_scheduler: BackgroundScheduler | None = None


def _scheduled_job():
    """
    Wrapper run by APScheduler. Opens its own DB session since this runs
    outside any FastAPI request -- there's no `Depends(get_db)` to use here,
    so we manage the session lifecycle directly (mirroring how seed.py and
    init_db.py already do this elsewhere in the project).
    """
    db = SessionLocal()
    try:
        run = run_clustering_pipeline(db, triggered_by_user_id=None, trigger_source="scheduler")
        print(f"[clustering scheduler] Run {run.run_id} finished with status={run.status}.")
    except Exception as exc:
        # run_clustering_pipeline already handles expected failure paths
        # internally (insufficient data, embedding/clustering errors) by
        # writing a failed ClusteringRun row. This except is a last-resort
        # safety net for truly unexpected errors (e.g. DB connection lost)
        # so one bad run can never crash the scheduler thread and silently
        # stop all future scheduled runs.
        print(f"[clustering scheduler] Unexpected error during scheduled run: {exc!r}")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    """
    Starts the background scheduler. Call once from main.py's startup.

    Runs daily at settings.CLUSTERING_SCHEDULE_HOUR (24-hour, server-local
    time) -- a single daily run is enough cadence for a campus chatbot's
    query volume, and avoids re-embedding/re-clustering the same backlog
    needlessly throughout the day.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler  # idempotent -- avoid double-scheduling on reload

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _scheduled_job,
        trigger=CronTrigger(hour=settings.CLUSTERING_SCHEDULE_HOUR, minute=0),
        id="daily_clustering_run",
        replace_existing=True,
    )
    _scheduler.start()
    print(f"[clustering scheduler] Started. Daily run scheduled for {settings.CLUSTERING_SCHEDULE_HOUR}:00 UTC.")
    return _scheduler


def stop_scheduler():
    """Call from main.py's shutdown so the background thread exits cleanly."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def trigger_clustering_manually(db, admin_user_id: int):
    """
    Runs the clustering pipeline immediately, synchronously, on the caller's
    existing request-scoped DB session. Used by the admin "Run Clustering Now"
    action (e.g. a future POST /api/clusters/run endpoint, and the manual-
    trigger path implied by the "Admin" actor's "Schedule Trigger" arrow in
    the system architecture diagram).

    Runs synchronously and can take noticeably long on a large backlog
    (embedding + LLM labeling calls) -- the calling endpoint should expect
    this and either await it directly for small schools, or, if response
    time becomes an issue, move this to a FastAPI BackgroundTask later.
    """
    return run_clustering_pipeline(db, triggered_by_user_id=admin_user_id, trigger_source="admin_manual")