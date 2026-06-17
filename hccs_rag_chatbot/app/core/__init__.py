
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings


engine = create_engine(
    f"sqlite:///{settings.SQLITE_DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a database session.
    Usage in an endpoint:
        def my_endpoint(db: Session = Depends(get_db)):
    The session is automatically closed after the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()