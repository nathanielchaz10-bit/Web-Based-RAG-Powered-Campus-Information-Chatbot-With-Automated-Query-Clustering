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

# Clusters smaller than this are left unclustered rather than shown as a
# tiny, noisy category on the dashboard.
MIN_CLUSTER_SIZE = 3

EMBEDDING_MODEL = "gemini-embedding-001"


def _choose_cluster_count(n: int) -> int:
    """Pick how many clusters to form from the number of queries.

    Uses a scaled sqrt heuristic (n_clusters ~= 1.5 * sqrt(n)), which scales
    smoothly as query volume grows: 41 queries -> 10 clusters, 100 -> 15,
    9 -> 5. The 1.5 multiplier yields finer-grained clusters; raise it for
    more clusters, lower it for fewer.
    """
    return max(3, min(n, round(np.sqrt(n) * 1.5)))


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

    Embeddings are computed exactly once per query and cached, so re-running
    the cluster engine never re-embeds the same text. task_type='CLUSTERING'
    produces vectors optimised for grouping rather than general similarity.
    """
    cursor.execute("SELECT query_id, query_text FROM user_queries WHERE embedding IS NULL")
    rows = cursor.fetchall()
    if not rows:
        return

    print(f"Embedding {len(rows)} new queries (caching vectors to DB)...")
    model = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, task_type="CLUSTERING")

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


def _flag_outliers(labels: np.ndarray, normed: np.ndarray) -> np.ndarray:
    """Mark per-cluster outliers as -1 (unclustered).

    Within each cluster, any query whose cosine distance to the cluster
    centroid is more than 2 standard deviations above the cluster mean is
    considered a poor fit and left unclustered instead of polluting the group.
    The 2-std threshold is conservative enough to only remove genuine oddballs.
    """
    result = labels.copy()
    for label in np.unique(labels):
        indices = np.where(labels == label)[0]
        if len(indices) < 2:
            continue
        centroid = normalize(normed[indices].mean(axis=0, keepdims=True))[0]
        # cosine distance = 1 - cosine similarity (vectors are already L2-normed)
        distances = 1.0 - normed[indices] @ centroid
        threshold = distances.mean() + 2.0 * distances.std()
        for idx, dist in zip(indices, distances):
            if dist > threshold:
                result[idx] = -1
    return result


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

    # 2. Load ALL queries — re-cluster the full set every run so there are no
    #    stale centroids from previous runs to corrupt the results.
    cursor.execute("SELECT query_id, query_text, embedding FROM user_queries WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()

    if len(rows) < MIN_CLUSTER_SIZE:
        print()
        print(f"Only {len(rows)} embedded queries — need at least {MIN_CLUSTER_SIZE} to cluster.")
        conn.close()
        return

    print()
    print(f"Clustering {len(rows)} queries.")

    ids   = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    vectors = np.array([json.loads(r[2]) for r in rows])

    # 3. Mean-center then L2-normalize.
    #    Gemini embeddings are anisotropic — all vectors lean in a broadly
    #    similar direction — so subtracting the global mean before normalizing
    #    spreads the space and sharpens cluster separation.
    vectors -= vectors.mean(axis=0)
    normed = normalize(vectors)

    # 4. Run Agglomerative Clustering.
    k = _choose_cluster_count(len(rows))
    print(f"Running Agglomerative Clustering into {k} clusters...")
    agg = AgglomerativeClustering(n_clusters=k, metric='euclidean', linkage='ward')
    labels = agg.fit_predict(normed)

    # 5. Flag per-cluster outliers as unclustered (-1) so genuine oddballs
    #    (e.g. a one-off question that doesn't fit any group) don't pollute a
    #    cluster and confuse the LLM naming step.
    labels = _flag_outliers(labels, normed)
    outlier_count = int(np.sum(labels == -1))
    if outlier_count:
        print(f"Outlier removal: {outlier_count} queries left unclustered as poor fits.")

    # 6. Full rebuild: wipe old clusters then recreate from scratch.
    cursor.execute("UPDATE user_queries SET cluster_id = NULL")
    cursor.execute("DELETE FROM query_clusters")
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='query_clusters'")
    except sqlite3.OperationalError:
        pass

    # 7. Name and persist each cluster (skip tiny ones)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    for label in sorted(set(labels) - {-1}):
        member_indices = [i for i, lbl in enumerate(labels) if lbl == label]
        questions = [texts[i] for i in member_indices]

        if len(questions) < MIN_CLUSTER_SIZE:
            print(f"Skipping cluster {label} ({len(questions)} queries — below minimum size of {MIN_CLUSTER_SIZE})")
            continue

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
