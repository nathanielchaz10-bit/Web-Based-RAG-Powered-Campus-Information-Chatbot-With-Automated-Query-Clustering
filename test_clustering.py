import sqlite3
import numpy as np
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

load_dotenv()

def run_agglomerative_test():
    print("Connecting to analytics database...")
    conn = sqlite3.connect('analytics.db')
    cursor = conn.cursor()

    # Fetch the exact same 41 questions
    cursor.execute("SELECT query_text FROM user_queries WHERE cluster_id IS NULL")
    unclustered_queries = cursor.fetchall()
    
    if not unclustered_queries:
        print("No queries to test!")
        conn.close()
        return

    query_texts = [q[0] for q in unclustered_queries]
    print(f"Found {len(query_texts)} questions. Generating vectors...")

    # Turn them into numbers
    embeddings_model = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
    vectors = embeddings_model.embed_documents(query_texts)
    normed = normalize(vectors)

    # The Distance Threshold Sweeper Loop
    print("\n--- Starting Agglomerative Clustering Test ---")
    # A lower threshold is strict (more clusters). A higher threshold is loose (fewer clusters).
    for thresh in np.arange(0.10, 0.45, 0.05):
        agg = AgglomerativeClustering(n_clusters=None, distance_threshold=thresh, metric='cosine', linkage='average')
        labels = agg.fit_predict(normed)
        num_clusters = len(set(labels))
        
        print(f"Testing distance_threshold={thresh:.2f} | Found {num_clusters} distinct clusters")

    conn.close()

if __name__ == "__main__":
    run_agglomerative_test()