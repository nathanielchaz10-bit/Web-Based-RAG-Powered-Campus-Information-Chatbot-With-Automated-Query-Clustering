# Web-Based RAG-Powered Campus Information Chatbot with Automated Query Clustering

A web application for Holy Child Catholic School that lets students ask
questions about campus information and get answers grounded in the school's own
documents (RAG), while automatically grouping the questions students ask into
topic clusters for an admin analytics dashboard.

The system is a **FastAPI** backend serving a static HTML/CSS/JS frontend:

- **RAG chatbot** — retrieval-augmented generation over the school's documents
  using ChromaDB + Google Gemini (embeddings + `gemini-2.5-flash`), with
  history-aware follow-up questions.
- **Automated query clustering** — an ML pipeline (Gemini embeddings →
  Agglomerative clustering → LLM labeling) that groups logged student queries
  into named topics. It runs on demand (admin) and on a daily schedule.
- **Admin dashboard** — live metrics, query volume, system health, and the
  cluster breakdown.
- **Auth** — Google OAuth with role-based access (student / admin), plus a
  dev-login bypass for local testing.

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy (SQLite), APScheduler
- **AI/ML:** LangChain, Google Gemini (`langchain-google-genai`), ChromaDB,
  scikit-learn (Agglomerative clustering), NumPy
- **Frontend:** static HTML / CSS / vanilla JS (served by FastAPI)

## Repository Layout

```
.
├── hccs_rag_chatbot/        # The web application (FastAPI backend + frontend)
├── src/                     # Shared engine code
│   └── rag_engine.py        # RAG pipeline (ChromaDB + Gemini, history-aware)
├── docs/                    # Source documents indexed by the RAG engine
├── db_tools/                # Database utility scripts (init/seed/reset)
├── scripts/                 # Misc utility / testing scripts
├── archive/                 # Retired / legacy code (kept for reference)
├── requirements.txt         # Full pinned dependency set
└── requirements-min.txt     # Slim subset — only what the app actually imports
```

### Inside `hccs_rag_chatbot/`

```
hccs_rag_chatbot/
├── main.py                  # FastAPI entry point (uvicorn target)
├── INTEGRATION.md           # How the RAG engine + clustering pipeline are wired in
│
├── app/
│   ├── api/                 # Route handlers
│   │   ├── auth.py          #   /api/auth/* (Google OAuth + dev-login)
│   │   ├── chat.py          #   POST /chat  (student chatbot)
│   │   ├── clusters.py      #   /clusters   (run + read clustering results)
│   │   ├── dashboard.py     #   /dashboard/* (admin analytics)
│   │   └── deps.py          #   shared dependencies (auth, roles)
│   │
│   ├── core/                # config, database session, security (JWT)
│   ├── models/              # SQLAlchemy ORM models (users, sessions, queries,
│   │                        #   responses, clusters, runs, metrics, ...)
│   └── services/
│       ├── rag/             # rag_service.py — wraps src/rag_engine.py
│       ├── clustering/      # the ML clustering pipeline:
│       │   ├── preprocessor.py   #   fetch/validate clusterable queries
│       │   ├── vectorizer.py      #   Gemini embeddings (batched, retrying)
│       │   ├── algorithm.py       #   Agglomerative clustering
│       │   ├── labeler.py         #   LLM names + describes each cluster
│       │   ├── pipeline.py        #   orchestrates one full run + persistence
│       │   └── scheduler.py       #   APScheduler daily run + manual trigger
│       ├── nlp/             # local sentiment + intent classification
│       ├── auth/            # Google OAuth + email-domain validation
│       └── _engine_bootstrap.py   # puts repo root on sys.path; bridges API key
│
├── database/                # DB init/seed/inspect helpers + hccs_rag.db
└── frontend/                # static site (login, student chat, admin pages)
    ├── index.html           #   login page
    ├── student/             #   student chatbot UI
    ├── admin/               #   dashboard, clusters, documents, settings pages
    ├── css/  └── js/         #   styles + page scripts
```

## Local Setup

Run everything from the **repository root** unless noted.

### 1. Clone

```bash
git clone https://github.com/nathanielchaz10-bit/Web-Based-RAG-Powered-Campus-Information-Chatbot-With-Automated-Query-Clustering
cd Web-Based-RAG-Powered-Campus-Information-Chatbot-With-Automated-Query-Clustering
```

### 2. Virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
# or, for a lighter install with only what the app imports:
# pip install -r requirements-min.txt
```

### 4. Configure environment variables

You need a Google Gemini API key (free tier from Google AI Studio works).

```bash
cp .env.example .env            # then edit .env
```

At minimum set `GEMINI_API_KEY` in `.env`. For real Google sign-in, also set
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` and
`DEV_MODE=False`. While `DEV_MODE=True`, the login page exposes a **DEV ONLY**
panel with Student / Admin buttons so no OAuth setup is needed locally.

### 5. Add source documents (RAG corpus)

Put the school's PDFs / DOCX files in the repo-root `docs/` folder. The RAG
engine builds its ChromaDB index from this folder on first run.

### 6. Run the app

```bash
cd hccs_rag_chatbot
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000/** (redirects to the login page). On startup the
database tables are auto-created, the default roles are seeded, and the daily
clustering scheduler starts. To start from a clean database, delete
`hccs_rag_chatbot/database/hccs_rag.db` and restart.

## Further Reading

See [`hccs_rag_chatbot/INTEGRATION.md`](hccs_rag_chatbot/INTEGRATION.md) for how
the RAG engine and clustering pipeline are wired into the backend, the key
implementation decisions, and what is not yet integrated.
```
