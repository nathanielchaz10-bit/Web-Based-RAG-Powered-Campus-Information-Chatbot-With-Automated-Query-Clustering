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
| Documents | `POST /documents/upload`, `GET /documents`, `POST /documents/{id}/approve`, `DELETE /documents/{id}` (admin) | Upload → tiered ingestion (`app/services/ingestion`: native text layer, Gemini-vision OCR for scanned PDFs) → incremental indexing into Chroma (`app/services/rag/indexer.py`). Confident extractions go live immediately; low-confidence or failed-indexing uploads are saved and held for review (retry via Approve). Writes `Document` + `DocumentChunk`. |
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
- **NLP enrichment (sentiment + intent) is local and zero-cost.** Each logged
  `QueryLog` is tagged at write time (`app/api/chat.py` → `app/services/nlp/`)
  with a `sentiment` bucket (VADER lexicon + an urgency-term override →
  *Positive / Inquisitive*, *Neutral / Transactional*, *Urgent / Frustrated*)
  and a `detected_intent` topic label (rule-based, word-boundary keyword
  scoring across 10 categories with a *General Inquiry* catch-all). Both run on
  the raw query string after the answer is generated and never block the chat
  turn — any failure degrades to a NULL column. Surfaced in the dashboard's
  Recent Student Inquiries table and the Query Clusters sentiment distribution.

## Not yet integrated (next steps)

- **Real Google OAuth.** The flow is fixed and ready, but needs real
  `GOOGLE_CLIENT_ID/SECRET` + redirect URI in `.env` and `DEV_MODE=False`.
- **Rate limiting (enforced, two layers).** `POST /chat` runs two in-memory
  sliding-window limiters before any Gemini call (`app/core/rate_limit.py`, via
  the `enforce_chat_rate_limit` dependency):
  - **Per-user front door** -> 429 when one user exceeds
    `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` (abuse / DDoS guard).
  - **Global back door** -> 503 when the whole server exceeds
    `RATE_LIMIT_GLOBAL_MAX_REQUESTS` / `RATE_LIMIT_GLOBAL_WINDOW_SECONDS`. This
    bounds total Gemini load (one student turn fans out to ~2 Flash + 4 embedding
    calls via RAG-Fusion), so size it ~= Flash RPM / 2.

  Thresholds come from `.env` defaults, but the **per-user rate-limit threshold
  is now admin-editable at runtime** via Portal Settings (see below) and applies
  to the next query with no restart.

- **Portal Settings (`GET`/`PUT /settings`, admin).** Admin-editable runtime
  config persisted to the `app_settings` key-value table (`app/models/
  app_setting.py`), with cast/validate/default logic in `app/core/
  settings_store.py` driven by a single `_SPECS` registry. The page exposes the
  three **rate-limit controls** — per-student threshold, time window, and the
  server-wide ceiling — all "live": saving writes back onto the `settings`
  object the chat limiters read each request (re-applied on startup so they
  survive restarts). RAG-engine parameters (temperature, relevance, context
  size) are intentionally NOT admin-editable — they shape answer quality and
  stay with the engine.

- **Admin Management (`/admins`, `app/api/admins.py`).** Backs the Portal
  Settings → Admin Management panel over real `UserAccount` + `Role` rows.
  `GET /admins` (any admin) lists admin-tier accounts; `POST /admins`,
  `PUT /admins/{id}`, and `POST /admins/{id}/status` are **Head-Admin-only**
  (`require_head_admin`). Add is a *pre-provision*: the row is created with a
  `pending:` placeholder `google_id` and the assigned role; on first Google
  sign-in the auth callback binds the real identity (and blocks deactivated
  accounts). Deactivation is a soft `is_active` flag enforced in
  `get_current_user`, with guards against deactivating yourself or the last
  Head Admin.
