

from pydantic_settings import BaseSettings

# placeholder
class Settings(BaseSettings):

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    HCCS_DOMAIN: str

    # Gemini API
    GEMINI_API_KEY: str
    EMBEDDING_MODEL: str
    LLM_MODEL: str

    # Database
    SQLITE_DB_PATH: str
    CHROMA_DB_PATH: str

    # Security
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_EXPIRE_MINUTES: int

    # RAG Configuration
    TOP_K_CHUNKS: int
    CHUNK_SIZE: int
    CHUNK_OVERLAP: int
    RELEVANCE_THRESHOLD: float
    RAG_TEMPERATURE: float
    MAX_CONTEXT_TOKENS: int

    # Rate Limiting
    RATE_LIMIT_MAX_REQUESTS: int
    RATE_LIMIT_WINDOW_SECONDS: int

    # Clustering
    CLUSTERING_MIN_QUERIES: int
    CLUSTERING_SCHEDULE_HOUR: int

    # Development Mode
    # Set to True during development and demo
    # Set to False in production to enforce HCCS domain restriction
    DEV_MODE: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()