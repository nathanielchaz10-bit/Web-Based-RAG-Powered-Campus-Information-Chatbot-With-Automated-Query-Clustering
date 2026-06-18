import os
import sqlite3

def view_clusters():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all clusters
    cursor.execute("SELECT cluster_id, cluster_name, cluster_summary FROM query_clusters")
    clusters = cursor.fetchall()

    if not clusters:
        print("No clusters found in the database. Run cluster_engine.py first!")
        return

    print("\n" + "="*50)
    print("STUDENT QUERY CLUSTERING REPORT")
    print("="*50)

    for cluster in clusters:
        cluster_id, name, summary = cluster
        print(f"\nCLUSTER: {name.upper()}")
        print(f"   Summary: {summary}")
        
        # Get all questions belonging to this cluster
        cursor.execute("SELECT query_text FROM user_queries WHERE cluster_id = ?", (cluster_id,))
        queries = cursor.fetchall()
        
        for q in queries:
            query_text = q[0]
            
            if " | Context:" in query_text:
                parts = query_text.split(" | Context:")
                clean_query = parts[0].replace("Question: ", "")
                full_context = parts[1].strip()
                
                # Grab just the first 60 characters of the context for a neat preview
                context_preview = full_context[:60] + "..." if len(full_context) > 60 else full_context
                
                print(f"   - {clean_query}")
                print(f"     (Context: {context_preview})")
            else:
                print(f"   - {query_text}")

    print("\n" + "="*50)
    conn.close()

if __name__ == "__main__":
    view_clusters()