# database/seed.py
# ─────────────────────────────────────────────────────────────────────────────
# Run this script AFTER init_db.py.
# Seeds the Role table with all default roles required by the system.
# Safe to run multiple times — checks if roles already exist before inserting.


import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.role import Role


def seed_roles(db):
    existing_roles = db.query(Role).all()
    existing_names = {r.role_name for r in existing_roles}

    roles_to_seed = [
        {
            "role_name": "Student",
            "description": (
                "Default role for all students authenticated via "
                "HCCS Google Workspace. Grants access to the "
                "student-facing chatbot interface only."
            )
        },
        {
            "role_name": "Head Admin",
            "description": (
                "Full system access including Admin Management, "
                "AI Configuration, Portal Settings, Document Directory, "
                "Query Clusters, and Dashboard Overview."
            )
        },
        {
            "role_name": "Registrar",
            "description": (
                "Operational access to Document Directory, "
                "Dashboard Overview, and Query Clusters. "
                "Cannot access Admin Management or AI Configuration."
            )
        },
        {
            "role_name": "Finance Officer",
            "description": (
                "Limited portal access. Can view Dashboard Overview "
                "and Document Directory. Cannot trigger clustering runs "
                "or access system configuration."
            )
        },
    ]

    seeded = []
    for role_data in roles_to_seed:
        if role_data["role_name"] not in existing_names:
            role = Role(**role_data)
            db.add(role)
            seeded.append(role_data["role_name"])

    if seeded:
        db.commit()
        print("Roles seeded:")
        for name in seeded:
            print(f"  ✓  {name}")
    else:
        print("All roles already exist — nothing to seed.")


def seed():
    db = SessionLocal()
    try:
        print("Seeding database...")
        print("")
        seed_roles(db)
        print("")
        print("Seeding complete.")
    except Exception as e:
        db.rollback()
        print(f"Seeding failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()