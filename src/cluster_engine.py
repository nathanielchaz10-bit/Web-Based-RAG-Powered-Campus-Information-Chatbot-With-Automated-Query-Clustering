import sqlite3
import os
import re
import time
import json
import numpy as np
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from sklearn.preprocessing import normalize

load_dotenv()

# Final clusters with fewer than this many queries are treated as one-off
# noise and left unclustered instead of cluttering the dashboard.
MIN_CLUSTER_SIZE = 3

# Two queries whose embeddings are at least this cosine-similar are treated as
# near-duplicates and collapsed to a single representative before the LLM step.
# Kept high so only genuine paraphrases ("what is the tuition" / "how much is
# tuition") merge — distinct questions are left for the LLM to judge.
DEDUP_THRESHOLD = 0.95

EMBEDDING_MODEL = "gemini-embedding-001"
LLM_MODEL = "gemini-2.5-flash"


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

    Embeddings here are only used to collapse near-duplicate queries before the
    LLM grouping step (keeping the prompt small and cheap). They are computed
    once per query and cached, so re-running never re-embeds the same text.
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


def _deduplicate(normed: np.ndarray):
    """Greedily group near-duplicate queries by cosine similarity.

    Returns a list of groups, each a list of original row indices. The first
    index in each group is its representative — the one query actually shown to
    the LLM. O(n^2), which is fine for the hundreds-to-low-thousands of queries
    a campus chatbot realistically accumulates.
    """
    n = len(normed)
    sim = normed @ normed.T
    assigned = [False] * n
    groups = []
    for i in range(n):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if not assigned[j] and sim[i, j] >= DEDUP_THRESHOLD:
                assigned[j] = True
                group.append(j)
        groups.append(group)
    return groups


def _llm_cluster(llm, rep_texts):
    """Ask the LLM to organize representative queries into named topic groups.

    Returns a list of {"name": str, "members": [int, ...]} dicts where members
    are indices into rep_texts. Retries on transient errors / bad JSON.
    """
    numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(rep_texts))
    prompt = (
        "You are organizing questions students asked a campus information "
        "chatbot into topic categories for an analytics dashboard.\n\n"
        "Here is a numbered list of questions:\n"
        f"{numbered}\n\n"
        "Group them into clear, distinct topic categories based on what the "
        "student actually wants (their intent), not just shared keywords. "
        "Keep closely related questions together — for example, all questions "
        "about paying tuition (methods, installments, discounts, failed "
        "payments) belong in ONE payments category. Every question must be "
        "placed in exactly one category. Give each category a short, "
        "professional 2-3 word name (e.g. 'Payment Inquiries', 'Enrollment "
        "Process', 'Campus Facilities').\n\n"
        "Reply with ONLY valid JSON, no markdown, in exactly this format:\n"
        '[{"name": "Category Name", "members": [0, 3, 5]}, ...]'
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            raw = llm.invoke(prompt).content.strip()
            # Strip ```json ... ``` fences if the model added them
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
            groups = json.loads(raw)
            if isinstance(groups, list):
                return groups
            print("LLM returned unexpected JSON shape. Retrying.")
        except json.JSONDecodeError:
            print(f"Could not parse LLM response as JSON. Retrying. (Attempt {attempt + 1}/{max_retries})")
        except Exception:
            print(f"API Server busy. Retrying in 10 seconds. (Attempt {attempt + 1}/{max_retries})")
            time.sleep(10)
    print("Failed to get a valid grouping from the LLM.")
    return []


def run_clustering():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')

    print()
    print("Connecting to analytics database.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    _ensure_schema(conn, cursor)

    # 1. Make sure every query has a cached embedding (for dedup only)
    _embed_missing_queries(conn, cursor)

    # 2. Load ALL queries — we regroup the full set every run.
    cursor.execute("SELECT query_id, query_text, embedding FROM user_queries WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()

    if len(rows) < MIN_CLUSTER_SIZE:
        print()
        print(f"Only {len(rows)} embedded queries — need at least {MIN_CLUSTER_SIZE} to cluster.")
        conn.close()
        return

    print()
    print(f"Clustering {len(rows)} queries.")

    ids     = [r[0] for r in rows]
    texts   = [r[1] for r in rows]
    vectors = np.array([json.loads(r[2]) for r in rows])
    normed  = normalize(vectors)

    # 3. Collapse near-duplicate queries so the LLM sees each distinct question
    #    once. Each group's first member is its representative.
    dup_groups = _deduplicate(normed)
    rep_indices = [g[0] for g in dup_groups]
    rep_texts = [texts[i] for i in rep_indices]
    print(f"Deduplicated {len(rows)} queries down to {len(rep_texts)} distinct ones.")

    # 4. Let the LLM organize the representatives into topic groups by intent.
    print(f"Asking {LLM_MODEL} to group queries by topic...")
    llm = ChatGoogleGenerativeAI(model=LLM_MODEL, temperature=0)
    llm_groups = _llm_cluster(llm, rep_texts)

    if not llm_groups:
        print("No grouping produced; leaving database unchanged.")
        conn.close()
        return

    # 5. Full rebuild: wipe old clusters then recreate from the LLM grouping.
    cursor.execute("UPDATE user_queries SET cluster_id = NULL")
    cursor.execute("DELETE FROM query_clusters")
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='query_clusters'")
    except sqlite3.OperationalError:
        pass

    for group in llm_groups:
        name = str(group.get("name", "")).strip() or "Unnamed Cluster"
        members = group.get("members", [])

        # Expand each representative back to all its near-duplicate originals,
        # collecting the real query_ids that belong to this topic.
        member_query_ids = []
        for rep_pos in members:
            if not isinstance(rep_pos, int) or not (0 <= rep_pos < len(dup_groups)):
                continue  # ignore hallucinated / out-of-range indices
            for original_idx in dup_groups[rep_pos]:
                member_query_ids.append(ids[original_idx])

        # Leave tiny topics unclustered rather than surfacing noise
        if len(member_query_ids) < MIN_CLUSTER_SIZE:
            print(f"Skipping '{name}' ({len(member_query_ids)} queries — below minimum size of {MIN_CLUSTER_SIZE})")
            continue

        print(f"Generated Cluster: {name} ({len(member_query_ids)} queries)")
        cursor.execute(
            "INSERT INTO query_clusters (cluster_name, cluster_summary) VALUES (?, ?)",
            (name,
             f"Automatically generated cluster containing {len(member_query_ids)} queries."),
        )
        new_cluster_id = cursor.lastrowid

        for qid in member_query_ids:
            cursor.execute(
                "UPDATE user_queries SET cluster_id = ? WHERE query_id = ?",
                (new_cluster_id, qid),
            )

    conn.commit()
    conn.close()
    print("Clustering complete and database updated.")


if __name__ == "__main__":
    run_clustering()
