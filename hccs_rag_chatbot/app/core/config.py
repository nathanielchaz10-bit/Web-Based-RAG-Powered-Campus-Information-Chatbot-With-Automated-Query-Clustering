from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Path anchors (CWD-independent)
# config.py lives at: <repo>/hccs_rag_chatbot/app/core/config.py
#   parents[2] -> <repo>/hccs_rag_chatbot   (the app root, holds database/, uploads/)
#   parents[3] -> <repo>                     (repo root, holds chroma_db/)
# ---------------------------------------------------------------------------
APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Central configuration.

    Every field now has a sensible default so the FastAPI app boots even when
    .env is incomplete (e.g. during local testing / demos). Fill .env in for
    real Google OAuth + your own Gemini key. See .env.example for the full list.
    """

    # --- Google OAuth (only needed for the real Google login path) ----------
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    HCCS_DOMAIN: str = "hccs.edu.ph"

    # --- Gemini / LLM -------------------------------------------------------
    GEMINI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    LLM_MODEL: str = "gemini-2.5-flash"

    # --- Database -----------------------------------------------------------
    # Absolute paths by default so the app works no matter where it's launched.
    SQLITE_DB_PATH: str = str(APP_ROOT / "database" / "hccs_rag.db")
    CHROMA_DB_PATH: str = str(REPO_ROOT / "chroma_db")

    # Source documents for the RAG pipeline. Lives under the app root and is
    # organized into per-type subfolders (docs/, pdf/, txt/); the loader walks
    # it recursively, so dropping a file into any subfolder makes it ingestible.
    UPLOADS_PATH: str = str(APP_ROOT / "uploads")

    # --- Security / JWT -----------------------------------------------------
    JWT_SECRET_KEY: str = "dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- RAG configuration (mirror rag_engine.py where known) ---------------
    TOP_K_CHUNKS: int = 5
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    RELEVANCE_THRESHOLD: float = 0.7
    RAG_TEMPERATURE: float = 0.0
    MAX_CONTEXT_TOKENS: int = 4000

    # --- RAG-Fusion (multi-query retrieval + reciprocal rank fusion) ---------
    # When enabled, one Flash call rewrites the (possibly Taglish/Tagalog,
    # possibly follow-up) question into RAG_FUSION_NUM_QUERIES standalone
    # English search queries; each is retrieved independently and the ranked
    # lists are merged with Reciprocal Rank Fusion before answering. Toggle off
    # to fall back to the single-query history-aware path. The extra cost lands
    # almost entirely on embeddings (high quota), not Flash calls.
    RAG_FUSION_ENABLED: bool = True
    RAG_FUSION_NUM_QUERIES: int = 4
    # RRF dampening constant (Cormack et al., 2009); 60 is the canonical value.
    RAG_FUSION_RRF_K: int = 60

    # --- Document ingestion (app/services/ingestion) ------------------------
    # Tiered extraction: try the cheap native text layer first; if a PDF looks
    # scanned (too few characters per page) fall back to OCR; optionally run an
    # LLM cleanup pass on OCR output. All of this is INGESTION-time, never on
    # the query path.
    # OCR engine: "gemini" (vision model -- better on table/grid layouts, no
    # system dependency, reuses our existing Gemini stack) or "tesseract"
    # (local, free, offline; kept as a pluggable fallback). Gemini is the
    # default because our scanned source documents are table-heavy, where
    # traditional OCR loses structure (see scripts/compare_ocr.py).
    INGEST_OCR_BACKEND: str = "gemini"
    # Below this many characters per page, a PDF's text layer is treated as
    # scanned/empty and OCR kicks in.
    INGEST_TEXT_MIN_CHARS_PER_PAGE: int = 100
    # After OCR, still below this many chars/page => flag the doc for human
    # review (genuinely unreadable source).
    INGEST_OCR_MIN_CHARS_PER_PAGE: int = 50
    # Render resolution for OCR; higher = more accurate but slower/heavier.
    INGEST_OCR_DPI: int = 300
    # Run an LLM cleanup pass over OCR output (reformat tables, fix OCR noise).
    INGEST_LLM_CLEANUP: bool = False

    # --- Rate limiting ------------------------------------------------------
    RATE_LIMIT_MAX_REQUESTS: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # --- Clustering (app/services/clustering) -------------------------------
    CLUSTERING_MIN_QUERIES: int = 3
    CLUSTERING_SCHEDULE_HOUR: int = 2

    # Minimum members for a group to survive as a cluster. Smaller groups are
    # dropped as one-off noise rather than surfaced on the dashboard.
    CLUSTERING_MIN_CLUSTER_SIZE: int = 3

    # Cosine DISTANCE at which clusters stop merging (distance = 1 - cosine
    # similarity), applied to the MEAN-CENTERED embeddings (see algorithm.py;
    # centering is what makes a single threshold workable on anisotropic Gemini
    # vectors). Lower -> more, tighter clusters; higher -> fewer, broader.
    # Because centering pushes unrelated pairs apart, the useful value lives
    # higher than it would on raw vectors. 0.85 was tuned on real cached vectors
    # (8 balanced topic clusters, ~82% coverage, just below where topics start
    # merging into blobs). Re-tune with `python scripts/tune_threshold.py` if you change
    # embedding models or your query mix shifts.
    CLUSTERING_DISTANCE_THRESHOLD: float = 0.85

    # --- Archived LLM-clustering experiment ---------------------------------
    # The pipeline uses agglomerative clustering only. An LLM-based alternative
    # was evaluated and archived under archive/llm_clustering_experiment/ (the
    # bake-off found no quality gain at scale and significant run-to-run
    # instability). These two settings are read solely by those archived
    # evaluation scripts and are otherwise unused by the running app.
    CLUSTERING_DEDUP_THRESHOLD: float = 0.95
    CLUSTERING_LLM_MAX_ITEMS: int = 400

    # --- Development Mode ----------------------------------------------------
    # True during development/demo: enables the dev-login bypass and relaxes the
    # HCCS domain restriction. Set False in production.
    DEV_MODE: bool = True

    # Look for .env in BOTH the repo root and the app root (hccs_rag_chatbot/),
    # since the app is launched from inside hccs_rag_chatbot/ and a .env is just
    # as likely to live there. Without this, a misplaced .env loads fine for the
    # chat path (which calls load_dotenv) but leaves these settings on defaults
    # — e.g. an empty GEMINI_API_KEY — which silently breaks the clustering path.
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(APP_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
