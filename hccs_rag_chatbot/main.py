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

from app.core.database import Base, engine, SessionLocal
import app.models  # noqa: F401  (registers all ORM models on Base.metadata)
from app.api import auth, chat, clusters, dashboard
from app.api.deps import ensure_roles

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = FastAPI(title="HCCS RAG Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # Create any missing tables and make sure the default roles exist so the
    # app is usable against a fresh database with zero manual setup.
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_roles(db)
    finally:
        db.close()


# --- API routers ------------------------------------------------------------
# auth lives under /api/auth/* (the frontend's auth.js calls http://host/api/...)
app.include_router(auth.router, prefix="/api")
# chat / clusters / dashboard are called via api.js (BASE_URL has no /api prefix)
app.include_router(chat.router)
app.include_router(clusters.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/frontend/index.html")


# --- Static frontend --------------------------------------------------------
# Mounted last so it doesn't shadow the API routes above.
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
