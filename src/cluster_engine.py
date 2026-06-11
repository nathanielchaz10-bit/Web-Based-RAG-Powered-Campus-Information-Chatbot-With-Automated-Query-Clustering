import sqlite3
import os
import time
import json
import numpy as np
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

load_dotenv()

MIN_CLUSTER_SIZE = 3

def run_clustering(distance_threshold=0.22):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')

    print()
    print("Connecting to analytics database.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Migrate schema: add centroid column if it doesn't exist yet
    try:
        cursor.execute("ALTER TABLE query_clusters ADD COLUMN centroid BLOB")
        conn.commit()
        print("Added centroid column to query_clusters.")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # 1. Fetch queries that haven't been clustered yet
    cursor.execute("SELECT query_id, query_text FROM user_queries WHERE cluster_id IS NULL")
    unclustered_queries = cursor.fetchall()

    if not unclustered_queries:
        print()
        print("No new queries to cluster.")
        conn.close()
        return

    print()
    print(f"Found {len(unclustered_queries)} new queries.")
    print("Starting clustering process.")

    # 2. Embed the queries
    query_texts = [q[1] for q in unclustered_queries]
    embeddings_model = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")

    vectors = []
    batch_size = 90
    for i in range(0, len(query_texts), batch_size):
        batch_texts = query_texts[i : i + batch_size]
        print(f"Processing batch {i} to {i + len(batch_texts)}.")
        batch_vectors = embeddings_model.embed_documents(batch_texts)
        vectors.extend(batch_vectors)

        if i + batch_size < len(query_texts):
            print("Approaching API limit. Sleeping for 60 seconds.")
            time.sleep(60)

    # 3. Perform Agglomerative Clustering
    print("Normalizing vectors and running Agglomerative Clustering...")
    normed = normalize(np.array(vectors))
    agg = AgglomerativeClustering(n_clusters=None,
                                  distance_threshold=distance_threshold,
                                  metric='euclidean',
                                  linkage='ward')
    labels = agg.fit_predict(normed)

    num_clusters = len(set(labels))
    print(f"Algorithm dynamically identified {num_clusters} distinct categories.")

    # 4. Load existing cluster centroids from the DB for cross-run merging
    cursor.execute("SELECT cluster_id, centroid FROM query_clusters WHERE centroid IS NOT NULL")
    existing_clusters = cursor.fetchall()
    existing_centroids = []
    for cid, blob in existing_clusters:
        centroid = np.array(json.loads(blob))
        existing_centroids.append((cid, centroid))

    # 5. Use Gemini to name and save each new cluster
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    for cluster_num in range(num_clusters):
        cluster_indices = [i for i, label in enumerate(labels) if label == cluster_num]
        cluster_questions = [query_texts[i] for i in cluster_indices]
        cluster_vectors = normed[cluster_indices]

        # Skip clusters that are too small — leave those queries unclustered for next run
        if len(cluster_questions) < MIN_CLUSTER_SIZE:
            print(f"Skipping cluster {cluster_num} ({len(cluster_questions)} queries — below minimum size of {MIN_CLUSTER_SIZE})")
            continue

        # Compute this cluster's centroid
        new_centroid = normalize(cluster_vectors.mean(axis=0, keepdims=True))[0]

        # Check against existing cluster centroids (cross-run merging)
        merged_into = None
        MERGE_THRESHOLD = 0.85
        for existing_id, existing_centroid in existing_centroids:
            similarity = float(np.dot(new_centroid, existing_centroid))
            if similarity >= MERGE_THRESHOLD:
                merged_into = existing_id
                print(f"Cluster {cluster_num} is similar to existing cluster {existing_id} (similarity={similarity:.2f}). Merging.")
                break

        if merged_into is not None:
            # Assign queries to the existing cluster
            for i in cluster_indices:
                query_id = unclustered_queries[i][0]
                cursor.execute("UPDATE user_queries SET cluster_id = ? WHERE query_id = ?", (merged_into, query_id))

            # Update the existing cluster's centroid to include new data
            cursor.execute("SELECT centroid FROM query_clusters WHERE cluster_id = ?", (merged_into,))
            old_centroid = np.array(json.loads(cursor.fetchone()[0]))
            updated_centroid = normalize(((old_centroid + new_centroid) / 2).reshape(1, -1))[0]
            cursor.execute("UPDATE query_clusters SET centroid = ? WHERE cluster_id = ?",
                           (json.dumps(updated_centroid.tolist()), merged_into))
        else:
            # Generate a name for the new cluster
            prompt = f"Look at these questions asked by students: {cluster_questions}. What is a short, 2-3 word professional category name for these questions? (e.g., 'Financial Inquiries', 'Grading Policies'). Reply with ONLY the name."

            cluster_name = "Unnamed Cluster"
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    cluster_name = llm.invoke(prompt).content.strip()
                    break
                except Exception as e:
                    print(f"API Server busy. Retrying in 10 seconds. (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(10)
                    if attempt == max_retries - 1:
                        print("Failed to get name from Gemini. Using default name.")

            print(f"Generated Cluster: {cluster_name} ({len(cluster_questions)} queries)")

            cursor.execute(
                "INSERT INTO query_clusters (cluster_name, cluster_summary, centroid) VALUES (?, ?, ?)",
                (cluster_name,
                 f"Automatically generated cluster containing {len(cluster_questions)} queries.",
                 json.dumps(new_centroid.tolist()))
            )
            new_cluster_id = cursor.lastrowid

            for i in cluster_indices:
                query_id = unclustered_queries[i][0]
                cursor.execute("UPDATE user_queries SET cluster_id = ? WHERE query_id = ?", (new_cluster_id, query_id))

            existing_centroids.append((new_cluster_id, new_centroid))

    conn.commit()
    conn.close()
    print("Clustering complete and database updated.")

if __name__ == "__main__":
    run_clustering()
