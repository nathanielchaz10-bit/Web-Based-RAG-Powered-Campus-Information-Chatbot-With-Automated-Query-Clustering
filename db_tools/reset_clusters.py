import sqlite3
import os

def reset_clusters():
    """Clear clusters only, keeping all logged queries.

    Deletes every row from query_clusters and sets cluster_id back to NULL on
    all user_queries, so the next cluster-engine run starts from a clean slate
    without losing any of the actual questions students asked. Use this after
    changing clustering parameters, instead of reset_db.py (which also wipes
    the queries themselves).
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, 'analytics.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Unlink every query from its cluster (keeps the queries themselves)
        cursor.execute("UPDATE user_queries SET cluster_id = NULL")
        unlinked = cursor.rowcount

        # 2. Remove all cluster rows and reset their ID counter back to 1
        cursor.execute("DELETE FROM query_clusters")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='query_clusters'")

        conn.commit()
        conn.close()
        print(f"Success: cleared all clusters and reset {unlinked} queries to unclustered.")
        print("Your logged queries are intact. Re-run the cluster engine to rebuild clusters.")

    except Exception as e:
        print(f"Error resetting clusters: {e}")

if __name__ == "__main__":
    reset_clusters()
