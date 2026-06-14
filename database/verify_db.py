import os
import sys

# Point Python to the root folder
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, engine
from app.models.role import Role


def verify():
    print("\n" + "=" * 40)
    print("DATABASE TRUTH TELLER")
    print("=" * 40)

    db_path = os.path.abspath(engine.url.database)
    print(f"Exact File Path: {db_path}")
    print(f"Does this file exist? {os.path.exists(db_path)}")
    print("-" * 40)

    try:
        db = SessionLocal()
        roles = db.query(Role).all()

        if len(roles) == 0:
            print("Status: Database is connected, but the roles table is EMPTY.")
        else:
            print(f"Status: SUCCESS! Found {len(roles)} Roles:")
            for r in roles:
                print(f"  ✓ {r.role_name}")
    except Exception as e:
        print(f"Error reading database: {e}")
    finally:
        db.close()
    print("=" * 40 + "\n")


if __name__ == "__main__":
    verify()