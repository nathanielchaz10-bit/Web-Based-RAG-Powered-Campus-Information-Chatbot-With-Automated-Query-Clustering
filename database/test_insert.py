import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.role import Role
from app.models.user_account import UserAccount


def test_insert_user():
    db = SessionLocal()
    try:
        student_role = db.query(Role).filter(Role.role_name == "Student").first()

        if not student_role:
            print("❌ Error: 'Student' role not found. Did you run seed.py?")
            return

        # Create a mock user object
        new_user = UserAccount(
            email="justine.test@hccs.edu.ph",
            role_id=student_role.role_id,
            google_id="mock_google_oauth_id_999",  # Satisfies the NOT NULL constraint
            display_name="Justine"  # Matches the column name in your model
        )

        # Add to the session and commit (save) to the database
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        print(f"✅ SUCCESS! Inserted test user '{new_user.email}' with Role ID: {new_user.role_id}")

    except Exception as e:
        db.rollback()  # Protect the database if it crashes
        print(f"❌ Insertion failed: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    test_insert_user()