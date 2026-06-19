from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Path anchors (CWD-independent)
# config.py lives at: <repo>/hccs_rag_chatbot/app/core/config.py
#   parents[2] -> <repo>/hccs_rag_chatbot   (the app root, holds database/)
#   parents[3] -> <repo>                     (repo root, holds docs/, chroma_db/)
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

    # --- Rate limiting ------------------------------------------------------
    RATE_LIMIT_MAX_REQUESTS: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # --- Clustering (app/services/clustering) -------------------------------
    CLUSTERING_MIN_QUERIES: int = 3
    CLUSTERING_SCHEDULE_HOUR: int = 2

    # Minimum members for a group to survive as a cluster (shared by BOTH
    # methods). Smaller groups are dropped as one-off noise rather than
    # surfaced on the dashboard.
    CLUSTERING_MIN_CLUSTER_SIZE: int = 3

    # Which grouping strategy the pipeline uses to decide *which queries go
    # together*. Both share the same embedding + LLM-labeling steps; only the
    # grouping differs:
    #   "agglomerative" -> sklearn AgglomerativeClustering on the embeddings
    #                      (deterministic, cheap, scales freely; groups by
    #                      embedding proximity).
    #   "llm"           -> embeddings collapse near-duplicates, then the LLM
    #                      groups the distinct queries by *intent* (better
    #                      topic quality; non-deterministic; costs LLM calls).
    # See app/services/clustering/algorithm.py vs algorithm_llm.py.
    CLUSTERING_METHOD: str = "agglomerative"

    # --- Agglomerative method tuning (ignored when METHOD != "agglomerative") -
    # Cosine DISTANCE at which clusters stop merging (distance = 1 - cosine
    # similarity). Two queries merge when their similarity is roughly
    # >= (1 - threshold). Lower -> more, tighter clusters; higher -> fewer,
    # broader (too high merges everything into one blob).
    # The right value depends on your embeddings' distribution: Gemini
    # embeddings are anisotropic (even unrelated queries sit fairly similar),
    # so a smallish threshold is needed to separate topics. Run
    # `python tune_threshold.py` to sweep this against your own cached vectors
    # and pick the value that yields a sensible number of clusters.
    CLUSTERING_DISTANCE_THRESHOLD: float = 0.25

    # --- LLM clustering method tuning (ignored when METHOD != "llm") --------
    # Two queries whose normalized embeddings are at least this cosine-similar
    # are treated as near-paraphrases and collapsed to one representative
    # before the LLM grouping step, keeping the prompt small. Kept high so only
    # genuine duplicates merge ("what is the tuition" / "how much is tuition").
    CLUSTERING_DEDUP_THRESHOLD: float = 0.95

    # Scale safety net: once the number of *distinct* (post-dedup) queries
    # exceeds this, the LLM grouping switches from a single prompt to a
    # chunk-then-merge strategy so we never blow the model's context window.
    # Sized for the ~1k–2k peak this deployment targets.
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
