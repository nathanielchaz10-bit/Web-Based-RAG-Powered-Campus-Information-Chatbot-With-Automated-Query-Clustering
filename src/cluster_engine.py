import sqlite3
import os
import time
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

load_dotenv()

def run_clustering():
    print()
    print("Connecting to analytics database.")
    conn = sqlite3.connect('analytics.db')
    cursor = conn.cursor()

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
    
    # 2. Extract just the text and turn them into numbers (Embeddings)
    query_texts = [q[1] for q in unclustered_queries]
    embeddings_model = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
    
    # Batching to protect API limits
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
    normed = normalize(vectors)
    agg = AgglomerativeClustering(n_clusters=None, 
                                  distance_threshold=0.22, 
                                  metric='cosine', 
                                  linkage='ward')
    labels = agg.fit_predict(normed)

    # Calculate how many distinct clusters were dynamically formed
    num_clusters = len(set(labels))
    print(f"Algorithm dynamically identified {num_clusters} distinct categories.")

    # 4. Use Gemini to name each cluster
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    for cluster_num in range(num_clusters):
        # Gather all questions that fell into this specific group
        cluster_questions = [query_texts[i] for i, label in enumerate(labels) if label == cluster_num]
        
        # Ask the LLM to give this group an appropriate name
        prompt = f"Look at these questions asked by students: {cluster_questions}. What is a short, 2-3 word professional category name for these questions? (e.g., 'Financial Inquiries', 'Grading Policies'). Reply with ONLY the name."
        
        cluster_name = "Unnamed cluster"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                cluster_name = llm.invoke(prompt).content.strip()
                break  # Exit the retry loop if successful
            except Exception as e:
                print(f"API Server busy. Retrying in 10 seconds. (Attempt {attempt + 1}/{max_retries})")
                time.sleep(10)
                if attempt == max_retries - 1:
                    print("Failed to get name from Gemini. Using default name.")
        
        print(f"Generated Cluster: {cluster_name} ({len(cluster_questions)} queries)")

        # 5. Save the new cluster to the database
        cursor.execute("INSERT INTO query_clusters (cluster_name, cluster_summary) VALUES (?, ?)", 
                       (cluster_name, f"Automatically generated cluster containing {len(cluster_questions)} queries."))
        new_cluster_id = cursor.lastrowid

        # 6. Update the user_queries table to link them to this new cluster
        for i, label in enumerate(labels):
            if label == cluster_num:
                query_id = unclustered_queries[i][0]
                cursor.execute("UPDATE user_queries SET cluster_id = ? WHERE query_id = ?", (new_cluster_id, query_id))

    conn.commit()
    conn.close()
    print("Clustering complete and database updated.")

if __name__ == "__main__":
    run_clustering()