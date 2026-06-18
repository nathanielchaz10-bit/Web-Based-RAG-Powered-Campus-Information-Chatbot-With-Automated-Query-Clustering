# database/init_db.py

# Run this script before seed.py


import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base, engine

from app.models import (
    Role,
    SystemMetrics,
    UserAccount,
    AuthenticationLog,
    ChatSession,
    Document,
    ClusteringRun,
    DocumentChunk,
    Cluster,
    ClusterKeyword,
    QueryLog,
    ChatResponse,
)


def init():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("")
    print("Tables created successfully:")
    for table_name in Base.metadata.tables.keys():
        print(f"  ✓  {table_name}")
    print("")
    print("Database initialized at:", engine.url)


if __name__ == "__main__":
    init()