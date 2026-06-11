import sqlite3
import os

def reset_database():
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, 'analytics.db')
        conn = sqlite3.connect(db_path)
        
        cursor = conn.cursor()

        # 1. Delete all rows from both tables
        cursor.execute("DELETE FROM user_queries")
        cursor.execute("DELETE FROM query_clusters")

        # 2. Reset the auto-increment ID counters back to 1
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='user_queries' OR name='query_clusters'")

        conn.commit()
        conn.close()
        print("Success: All test data has been wiped. The database is empty and IDs are reset to 1.")

    except Exception as e:
        print(f"Error resetting database: {e}")

if __name__ == "__main__":
    reset_database()