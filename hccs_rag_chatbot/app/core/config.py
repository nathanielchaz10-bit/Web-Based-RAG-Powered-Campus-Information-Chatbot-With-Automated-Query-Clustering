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

    # Developer/owner emails granted Head Admin on real Google sign-in AND allowed
    # past the @HCCS_DOMAIN gate — so the maintainers' personal accounts can
    # administer a DEV_MODE=False deployment without the dev bypass. Comma-
    # separated, case-insensitive. On a fresh deployment this is the ONLY way a
    # Head Admin comes to exist, so set at least one before going live.
    BOOTSTRAP_ADMIN_EMAILS: str = ""

    @property
    def bootstrap_admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.BOOTSTRAP_ADMIN_EMAILS.split(",") if e.strip()}

    # --- Guest mode ---------------------------------------------------------
    # Visitors without an @hccs.edu.ph account get a restricted chatbot that
    # answers ONLY from these document categories (see chat.py:/chat/guest).
    # Comma-separated Document.document_type values.
    GUEST_DOCUMENT_TYPES: str = "ENROLLMENT,FINANCIAL"

    @property
    def guest_document_types(self) -> set[str]:
        return {t.strip().upper() for t in self.GUEST_DOCUMENT_TYPES.split(",") if t.strip()}

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

    # --- CORS ---------------------------------------------------------------
    # Comma-separated list of allowed browser origins for the API. The frontend
    # is served same-origin by this app (and behind the tunnel), so CORS is
    # largely moot in deployment; "*" stays the permissive default for local dev
    # (e.g. opening a page from disk). Lock it to the tunnel URL if you ever call
    # the API cross-origin. The app authenticates with a Bearer header, not
    # cookies, so credentialed CORS is intentionally off.
    CORS_ALLOW_ORIGINS: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

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
    # Per-page OCR: even inside an otherwise-digital PDF, OCR a single page when a
    # raster image covers at least this fraction of it AND the page carries little
    # text (a scanned page / figure / screenshot dropped into a digital document).
    INGEST_PAGE_IMAGE_COVERAGE: float = 0.5
    # docx embedded-image OCR: a .docx's pictures live in its zip under
    # word/media/. We OCR those too (text trapped in diagrams/screenshots), but
    # skip images smaller than this many pixels (area) so logos/icons don't add
    # noise. 50_000 ~= a 224x224 image.
    INGEST_DOCX_MIN_IMAGE_PIXELS: int = 50_000

    # --- Rate limiting ------------------------------------------------------
    # Two layers (see app/core/rate_limit.py). One student "send" fans out into
    # ~2 Flash + 4 embedding Gemini calls via RAG-Fusion, so the per-user send
    # limit alone is a coarse proxy for actual Gemini load.
    #
    # Per-user "front door": max queries one authenticated user may submit per
    # window (abuse / DDoS guard). 10/60s is ~1 message every 6s -- well above
    # human reading pace, so it never bites legitimate use but caps scripted spam.
    RATE_LIMIT_MAX_REQUESTS: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Global "back door": max chat turns the whole server admits per window,
    # across ALL users, protecting the shared Gemini quota no matter how many
    # users arrive at once. With a fixed per-turn fan-out, this is effectively a
    # cap on calls to Google. Size it to your tier: roughly
    #   RATE_LIMIT_GLOBAL_MAX_REQUESTS ~= (Gemini Flash requests-per-minute) / 2
    # (each turn makes ~2 Flash calls). Lower it hard on the free tier; raise it
    # on paid. Set <= 0 to disable the global layer. 30/60s here is a safe demo
    # ceiling (~60 Flash + ~120 embedding calls/min server-wide).
    RATE_LIMIT_GLOBAL_MAX_REQUESTS: int = 30
    RATE_LIMIT_GLOBAL_WINDOW_SECONDS: int = 60

    # --- Daily budget protection (the real guard for a small Gemini budget) ---
    # The per-minute limiters above only cap bursts. With a fixed-dollar key,
    # the actual risk is CUMULATIVE spend over days, so these DAILY caps (counted
    # from QueryLog, so they survive restarts) are what protect the budget.
    #
    # Per-student daily cap: spreads a scarce budget fairly so a few heavy users
    # can't drain it. Set <= 0 to disable.
    RATE_LIMIT_USER_DAILY_MAX: int = 20
    # Server-wide daily cap: THE budget protector. Size it so cap * (days you run)
    # stays under the dollar budget. Gemini 2.5 Flash is ~$0.003-0.005 per turn,
    # so ~$10 ≈ 2,000-3,300 turns; over a 7-day run ≈ 300-450/day. Default 300
    # leaves headroom. When hit, chat pauses until the next UTC day. Google's
    # billing is the hard backstop. Set <= 0 to disable.
    RATE_LIMIT_GLOBAL_DAILY_MAX: int = 300
    # Manual kill switch: flip to False (or toggle in Portal Settings) to pause
    # the chatbot for everyone instantly, without stopping the server.
    CHAT_ENABLED: bool = True

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
    # Opt-in, and OFF by default so a misconfigured/absent .env fails SAFE rather
    # than wide open. While True: a request with no/invalid token is treated as
    # Head Admin, /api/auth/dev-login mints admin tokens with no password, and the
    # HCCS domain restriction is relaxed. Set DEV_MODE=True in a LOCAL .env for
    # OAuth-free testing; never set it on the public deployment. Real admin access
    # in production comes from BOOTSTRAP_ADMIN_EMAILS above.
    DEV_MODE: bool = False

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
