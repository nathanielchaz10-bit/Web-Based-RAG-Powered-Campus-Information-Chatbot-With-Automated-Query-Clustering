
"""HCCS RAG Chatbot — FastAPI entrypoint.

Run from inside the hccs_rag_chatbot/ directory:
    uvicorn main:app --reload --port 8000

Wires the RAG + clustering engines (from the top-level src/ package) into the
relational backend and serves the static frontend.
"""

import os
import sys

# Force THIS directory (hccs_rag_chatbot/) to the front of sys.path so that
# `import app...` always resolves to the local app/ package, and is never
# shadowed by the repo-root streamlit script (app.py). uvicorn --reload can put
# the repo root on the path, which otherwise causes `import app` to load app.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.core.migrations import run_migrations
import app.models  # noqa: F401  (registers all ORM models on Base.metadata)
from app.api import admins, auth, chat, clusters, dashboard, documents
from app.api import settings as settings_routes
from app.api.deps import ensure_roles
from app.core import settings_store
from app.services.clustering.scheduler import start_scheduler, stop_scheduler

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

# Default JWT signing key shipped in config.py / .env.example. With this key in
# place anyone can forge a Bearer token claiming role=Head Admin, so a real
# deployment must override it (enforced at startup below).
_DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production"

app = FastAPI(title="HCCS RAG Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Auth is a Bearer header, not cookies, so we don't need credentialed CORS —
    # and "*" origins with credentials is rejected by browsers anyway.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_authenticated_pages(request, call_next):
    """Tell the browser not to cache the signed-in pages.

    `no-store` keeps the authenticated student/admin pages out of the bfcache, so
    after logout the back button can't resurrect a rendered page from cache. The
    frontend's pageshow guard is the primary defense; this is belt-and-braces.
    The public login page (/frontend/index.html) is intentionally left cacheable.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/frontend/student") or path.startswith("/frontend/admin"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


def _check_security_posture() -> None:
    """Guardrails so the app can't be shared publicly while wide open.

    The dangerous combination is DEV_MODE on (anyone with no token is treated as
    Head Admin, dev-login mints admin tokens, the domain check is relaxed). That
    is fine locally but catastrophic behind a public link, so:

      * If DEV_MODE is OFF but the JWT secret is still the default, refuse to
        start — a forged Head-Admin token would otherwise be trivial.
      * If DEV_MODE is ON, print an unmissable banner so it is never silently
        left on when the app gets exposed through the tunnel.
    """
    if not settings.DEV_MODE and settings.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "Refusing to start: DEV_MODE is off but JWT_SECRET_KEY is still the "
            "default value. Generate a strong secret and set it in .env "
            "(see DEPLOY.md). Anyone can forge admin tokens with the default key."
        )
    if settings.DEV_MODE:
        # ASCII only: this prints to the Windows console (cp1252), which can't
        # encode emoji/em-dashes.
        print("\n" + "=" * 72)
        print("  [!] DEV_MODE IS ON -- DO NOT SHARE THIS APP PUBLICLY")
        print("      - A request with no/invalid token is treated as HEAD ADMIN")
        print("      - /api/auth/dev-login mints admin tokens with no password")
        print("      - The @%s sign-in restriction is RELAXED" % settings.HCCS_DOMAIN)
        print("      Set DEV_MODE=False in .env before exposing the tunnel link.")
        print("=" * 72 + "\n")


@app.on_event("startup")
def on_startup():
    # Fail fast / warn loudly about an insecure configuration BEFORE serving.
    _check_security_posture()
    # Create any missing tables and make sure the default roles exist so the
    # app is usable against a fresh database with zero manual setup.
    Base.metadata.create_all(bind=engine)
    # create_all only creates missing TABLES; apply idempotent migrations so
    # existing databases pick up new columns/indexes too (no manual step).
    run_migrations(engine)
    db = SessionLocal()
    try:
        ensure_roles(db)
        # Apply any admin-saved overrides (e.g. the rate-limit threshold) onto
        # the live `settings` object so they survive restarts.
        settings_store.load_overrides_into_config(db)
    finally:
        db.close()

    # Start the background scheduler that runs the daily clustering job.
    start_scheduler()


# --- API routers ------------------------------------------------------------
# auth lives under /api/auth/* (the frontend's auth.js calls http://host/api/...)
app.include_router(auth.router, prefix="/api")
# chat / clusters / dashboard are called via api.js (BASE_URL has no /api prefix)
app.include_router(chat.router)
app.include_router(clusters.router)
app.include_router(dashboard.router)
app.include_router(documents.router)
app.include_router(settings_routes.router)
app.include_router(admins.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/frontend/index.html")


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()

app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
