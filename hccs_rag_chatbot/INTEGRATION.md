# Backend ↔ Engine Integration

This document describes how the RAG engine (`app/services/rag/rag_engine.py`)
and the query-clustering pipeline (`app/services/clustering/`) are wired into
the FastAPI app (`hccs_rag_chatbot/`) against the relational schema in
`hccs_rag.db`.

## Running locally

```bash
# from the repo root
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # put a real GEMINI_API_KEY in .env (free tier is fine)

cd hccs_rag_chatbot
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000/** (it redirects to the login page).

- The DB tables are auto-created and the four roles are seeded on startup.
- No Google OAuth setup is needed for local testing: the login page shows a
  **DEV ONLY** panel with "Student" / "Head Admin" buttons (works while
  `DEV_MODE=True`). These mint a real JWT for a seeded dev user.
- To start from a clean database, delete `hccs_rag_chatbot/database/hccs_rag.db`
  and restart — it will be recreated and reseeded.

## What was wired

| Area | Endpoint | Notes |
|------|----------|-------|
| Student chat | `POST /chat` | Calls `rag_engine` via `app/services/rag`. Logs `ChatSession` + `QueryLog` + `ChatResponse`. History is rebuilt server-side per session. |
| Clustering (run) | `POST /clusters/run` (admin) | Runs the ML clustering pipeline in `app/services/clustering` (`pipeline.py`): Gemini embeddings → Agglomerative clustering → LLM labeling. Writes `ClusteringRun` + `Cluster` + `ClusterKeyword`, back-fills `QueryLog.cluster_id`. Also runs daily via `scheduler.py`. |
| Clustering (read) | `GET /clusters` | Returns clusters of the latest completed run for the admin page. |
| Dashboard | `GET /dashboard/{metrics,query-volume,system-health,recent-inquiries}` (admin) | Computed live from the DB. |
| Auth | `/api/auth/{login,callback,me,logout,dev-login}` | Google path fixed (was importing a non-existent module) + dev-login bypass. |

Frontend wired: `student/chat.js`, `admin/clusters.js`, and the login page
(`auth.js`). `admin/dashboard.js` was already calling the right endpoints; it
now has `api.js`/`auth.js` loaded (they were missing).

## Key implementation decisions

- **`security.py` no longer uses `python-jose`** (it was never in
  `requirements.txt` and didn't install). It now mints/verifies standard HS256
  JWTs with the Python standard library — zero extra dependencies.
- **`app/core/config.py`** gives every setting a default so the app boots from
  an incomplete `.env`. Paths are absolute (CWD-independent).
- **`GEMINI_API_KEY` is bridged to `GOOGLE_API_KEY`** (the var langchain-google
  actually reads) in `app/services/_engine_bootstrap.py`.
- **The RAG engine (`app/services/rag/rag_engine.py`) is the single source of
  truth** for the retrieval chain; `app/services/rag/rag_service.py` wraps it
  and handles persistence against the SQLAlchemy models (it originally lived in
  a top-level `src/` package against a flat `analytics.db`).
- **Clustering is its own ML pipeline** under `app/services/clustering/`
  (`preprocessor` → `vectorizer` → `algorithm` → `labeler`, orchestrated by
  `pipeline.py`). It replaces the original `src/cluster_engine.py` LLM-grouping
  prototype, which was retired to `archive/` along with the Streamlit frontend.

## Not yet integrated (next steps)

- **Document upload → RAG ingestion.** RAG currently builds its ChromaDB index
  from the repo-root `docs/` folder (your original pipeline). The admin
  "Document Directory" page + `documents`/`document_chunks` tables are not yet
  connected to the vector store.
- **NLP enrichment.** `QueryLog.sentiment` / `detected_intent` are not populated
  yet, so the dashboard shows "Neutral"/"General" placeholders.
- **Real Google OAuth.** The flow is fixed and ready, but needs real
  `GOOGLE_CLIENT_ID/SECRET` + redirect URI in `.env` and `DEV_MODE=False`.
- **Rate limiting / scheduled clustering.** Config knobs exist; enforcement not
  wired.
