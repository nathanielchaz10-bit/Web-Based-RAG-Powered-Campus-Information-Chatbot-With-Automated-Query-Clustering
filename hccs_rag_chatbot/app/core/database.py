from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(
    f"sqlite:///{settings.SQLITE_DB_PATH}",
    # timeout: wait up to 15s for a write lock to clear instead of raising
    # "database is locked" immediately — SQLite serializes writes, and the
    # chat/clustering paths can contend under concurrent requests.
    connect_args={"check_same_thread": False, "timeout": 15},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()