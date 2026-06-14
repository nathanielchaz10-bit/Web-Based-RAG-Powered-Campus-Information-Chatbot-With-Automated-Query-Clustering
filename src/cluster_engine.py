import sqlite3
import os
import time
import json
import numpy as np
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import normalize

load_dotenv()

# Smallest group HDBSCAN will treat as a real cluster. Queries that don't fall
# into any cluster this size are labelled noise (-1) and left unclustered.
MIN_CLUSTER_SIZE = 3

# How conservative HDBSCAN is about declaring noise. Lower = fewer points
# dropped as noise, which suits the small query volumes a campus chatbot sees
# early on. 1 is the least conservative setting.
MIN_SAMPLES = 1

EMBEDDING_MODEL = "gemini-embedding-001"


def _ensure_schema(conn, cursor):
    """Add the cached-embedding column to user_queries if it isn't there yet."""
    try:
        cursor.execute("ALTER TABLE user_queries ADD COLUMN embedding BLOB")
        conn.commit()
        print("Added embedding column to user_queries.")
    except sqlite3.OperationalError:
        pass  # Column already exists


def _embed_missing_queries(conn, cursor):
    """Embed any queries with no cached vector yet and store them in the DB.

    Embeddings are computed exactly once per query and cached, so re-running the
    cluster engine never re-embeds the same text. This is what lets us safely
    re-cluster every query from scratch on each run.
    """
    cursor.execute("SELECT query_id, query_text FROM user_queries WHERE embedding IS NULL")
    rows = cursor.fetchall()
    if not rows:
        return

    print(f"Embedding {len(rows)} new queries (caching vectors to DB)...")
    model = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)

    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    batch_size = 90
    for i in range(0, len(texts), batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]
        print(f"Processing batch {i} to {i + len(batch_texts)}.")
        batch_vectors = model.embed_documents(batch_texts)

        for qid, vec in zip(batch_ids, batch_vectors):
            cursor.execute(
                "UPDATE user_queries SET embedding = ? WHERE query_id = ?",
                (json.dumps(vec), qid),
            )
        conn.commit()

        if i + batch_size < len(texts):
            print("Approaching API limit. Sleeping for 60 seconds.")
            time.sleep(60)


def _name_cluster(llm, questions):
    """Ask Gemini for a short category name, with retries on transient errors."""
    prompt = (
        f"Look at these questions asked by students: {questions}. "
        "What is a short, 2-3 word professional category name for these questions? "
        "(e.g., 'Financial Inquiries', 'Grading Policies'). Reply with ONLY the name."
    )
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return llm.invoke(prompt).content.strip()
        except Exception:
            print(f"API Server busy. Retrying in 10 seconds. (Attempt {attempt + 1}/{max_retries})")
            time.sleep(10)
    print("Failed to get name from Gemini. Using default name.")
    return "Unnamed Cluster"


def run_clustering():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')

    print()
    print("Connecting to analytics database.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    _ensure_schema(conn, cursor)

    # 1. Make sure every query has a cached embedding
    _embed_missing_queries(conn, cursor)

    # 2. Load ALL queries that have an embedding — we re-cluster the full set
    #    every run rather than incrementally merging, which avoids the stale
    #    centroid problems of the old cross-run merge approach.
    cursor.execute("SELECT query_id, query_text, embedding FROM user_queries WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()

    if len(rows) < MIN_CLUSTER_SIZE:
        print()
        print(f"Only {len(rows)} embedded queries — need at least {MIN_CLUSTER_SIZE} to cluster.")
        conn.close()
        return

    print()
    print(f"Clustering {len(rows)} queries.")

    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    vectors = np.array([json.loads(r[2]) for r in rows])

    # 3. Run HDBSCAN on L2-normalized vectors (euclidean distance on unit
    #    vectors is monotonic with cosine distance). HDBSCAN finds the number
    #    of clusters by itself and labels outliers as noise (-1).
    print("Normalizing vectors and running HDBSCAN...")
    normed = normalize(vectors)
    clusterer = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=MIN_SAMPLES,
        metric='euclidean',
    )
    labels = clusterer.fit_predict(normed)

    cluster_labels = sorted(set(labels) - {-1})
    noise_count = int(np.sum(labels == -1))
    print(f"HDBSCAN identified {len(cluster_labels)} clusters; "
          f"{noise_count} queries left unclustered as noise.")

    # 4. Full rebuild: clear old clusters and assignments, then recreate.
    cursor.execute("UPDATE user_queries SET cluster_id = NULL")
    cursor.execute("DELETE FROM query_clusters")
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='query_clusters'")
    except sqlite3.OperationalError:
        pass  # No AUTOINCREMENT counter yet

    if not cluster_labels:
        conn.commit()
        conn.close()
        print("No clusters met the minimum size this run. Database updated.")
        return

    # 5. Name and persist each cluster
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    for label in cluster_labels:
        member_indices = [i for i, lbl in enumerate(labels) if lbl == label]
        questions = [texts[i] for i in member_indices]

        cluster_name = _name_cluster(llm, questions)
        print(f"Generated Cluster: {cluster_name} ({len(questions)} queries)")

        cursor.execute(
            "INSERT INTO query_clusters (cluster_name, cluster_summary) VALUES (?, ?)",
            (cluster_name,
             f"Automatically generated cluster containing {len(questions)} queries."),
        )
        new_cluster_id = cursor.lastrowid

        for i in member_indices:
            cursor.execute(
                "UPDATE user_queries SET cluster_id = ? WHERE query_id = ?",
                (new_cluster_id, ids[i]),
            )

    conn.commit()
    conn.close()
    print("Clustering complete and database updated.")


if __name__ == "__main__":
    run_clustering()
