import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.role import Role


def check_roles():
    db = SessionLocal()
    roles = db.query(Role).all()

    print(f"\n--- Found {len(roles)} Roles in Database ---")
    for r in roles:
        print(f"ID: {r.role_id} | Name: {r.role_name} | Desc: {r.description[:30]}...")
    print("--------------------------------------\n")

    db.close()


if __name__ == "__main__":
    check_roles()