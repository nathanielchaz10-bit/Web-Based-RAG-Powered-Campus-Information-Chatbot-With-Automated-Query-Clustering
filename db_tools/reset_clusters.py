import sqlite3
import os

def reset_clusters(clear_embeddings: bool = False):
    """Clear clusters only, keeping all logged queries.

    Deletes every row from query_clusters and sets cluster_id back to NULL on
    all user_queries, so the next cluster-engine run starts from a clean slate
    without losing any of the actual questions students asked.

    Pass clear_embeddings=True (or --clear-embeddings on the CLI) after
    changing the embedding model or task_type, so cached vectors are refreshed
    on the next run.
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

        # 3. Optionally wipe the embedding cache (needed when embedding model
        #    or task_type changes so stale vectors get recomputed)
        if clear_embeddings:
            try:
                cursor.execute("UPDATE user_queries SET embedding = NULL")
                print(f"Cleared cached embeddings — they will be recomputed on the next run.")
            except sqlite3.OperationalError:
                pass  # embedding column doesn't exist yet, nothing to clear

        conn.commit()
        conn.close()
        print(f"Success: cleared all clusters and reset {unlinked} queries to unclustered.")
        print("Your logged queries are intact. Re-run the cluster engine to rebuild clusters.")

    except Exception as e:
        print(f"Error resetting clusters: {e}")


if __name__ == "__main__":
    import sys
    clear = "--clear-embeddings" in sys.argv
    reset_clusters(clear_embeddings=clear)
