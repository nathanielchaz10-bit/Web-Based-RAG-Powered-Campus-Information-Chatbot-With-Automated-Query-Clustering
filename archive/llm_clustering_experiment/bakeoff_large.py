"""
Large-scale bake-off: agglomerative vs LLM clustering on ~500 labeled queries.

Same idea as bakeoff.py but on the bigger, harder hand-authored dataset in
eval_dataset.py (16 topics + noise) instead of the 60-query seed set. This
probes whether the LLM's advantage holds at a more realistic scale and topic
count -- and exercises the LLM method's chunk-then-merge scale path.

It embeds the queries ONCE (Gemini, batched) and caches the vectors to disk, so
re-runs are instant and free. Scoring (ARI / NMI vs the true topics) reuses the
logic in bakeoff.py.

Run from inside hccs_rag_chatbot/:
    python bakeoff_large.py

Needs a working GEMINI_API_KEY. The first run embeds ~500 queries in batches
with cooldowns, so it can take a few minutes; subsequent runs use the cache.
Read-only with respect to the application database.
"""
import json
import os
import sys

import numpy as np
from sklearn.preprocessing import normalize

# Archived under archive/llm_clustering_experiment/; add the app root
# (hccs_rag_chatbot/) so `import app...` and `database...` still resolve.
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "hccs_rag_chatbot")))

import app.services._engine_bootstrap  # noqa: F401  bridges GEMINI->GOOGLE key

from app.core.config import settings
from app.services.clustering.vectorizer import embed_queries
from algorithm_llm import run_llm_clustering, _deduplicate  # archived sibling module
from eval_dataset import build_dataset
import bakeoff as B  # reuse score(), groups_to_pred(), agglomerative_at(), SWEEP

VEC_CACHE = "bakeoff_large_vectors.npy"
TXT_CACHE = "bakeoff_large_texts.json"
LLM_RUNS = 3


def get_embeddings(texts):
    """Embed once and cache; reload if the cached text list matches exactly."""
    if os.path.exists(VEC_CACHE) and os.path.exists(TXT_CACHE):
        with open(TXT_CACHE, encoding="utf-8") as fh:
            if json.load(fh) == texts:
                print("Loaded cached embeddings (delete bakeoff_large_*.* to refresh).")
                return np.load(VEC_CACHE)

    print(f"Embedding {len(texts)} queries via Gemini (cached afterwards). "
          "Batched with cooldowns — this may take a few minutes...")
    embedded = embed_queries(list(range(len(texts))), texts)
    vecs = np.array([v for _, v in embedded])
    np.save(VEC_CACHE, vecs)
    with open(TXT_CACHE, "w", encoding="utf-8") as fh:
        json.dump(texts, fh)
    return vecs


def run_llm_scored(ids, vecs, texts_by_id, topics, label):
    """Run the LLM method once and print its score; return (ari, nmi) or None."""
    try:
        with open(os.devnull, "w") as devnull, B.redirect_stdout(devnull):
            groups = run_llm_clustering(ids, vecs, texts_by_id)
    except Exception as exc:
        print(f"  {label}: FAILED ({exc}). Check GEMINI_API_KEY / quota.")
        return None
    s = B.score(groups, ids, topics)
    print(f"  {label}: clusters={s['clusters']}  ARI={s['ari']:.2f}  "
          f"NMI={s['nmi']:.2f}  coverage={s['coverage']:.0%}  "
          f"noise left unclustered={s['noise_correct']}/{s['noise_total']}")
    return s["ari"], s["nmi"]


def main():
    data = build_dataset()
    texts = [t for t, _ in data]
    topics = [top for _, top in data]
    ids = list(range(len(texts)))
    n = len(ids)
    n_topics = len({t for t in topics if t != "_noise"})
    n_noise = sum(1 for t in topics if t == "_noise")

    vecs = get_embeddings(texts)

    distinct = len(_deduplicate(normalize(vecs), settings.CLUSTERING_DEDUP_THRESHOLD))
    print(f"\nGround truth: {n_topics} topics across {n - n_noise} queries "
          f"(+ {n_noise} noise). dim={vecs.shape[1]}")
    print(f"Distinct after {settings.CLUSTERING_DEDUP_THRESHOLD} dedup: {distinct} "
          f"(LLM chunk-then-merge triggers above {settings.CLUSTERING_LLM_MAX_ITEMS}).\n")

    # ── Agglomerative sweep ─────────────────────────────────────────────
    print("AGGLOMERATIVE — threshold sweep (scored vs ground truth):")
    print(f"{'threshold':>9} | {'clusters':>8} | {'ARI':>5} | {'NMI':>5} | {'coverage':>8}")
    print("-" * 50)
    best = None
    for th in B.SWEEP:
        s = B.score(B.agglomerative_at(th, ids, vecs), ids, topics)
        print(f"{th:>9.3f} | {s['clusters']:>8} | {s['ari']:>5.2f} | "
              f"{s['nmi']:>5.2f} | {s['coverage']:>7.0%}")
        if best is None or s["ari"] > best[1]["ari"]:
            best = (th, s)

    cfg_th = settings.CLUSTERING_DISTANCE_THRESHOLD
    cfg = B.score(B.agglomerative_at(cfg_th, ids, vecs), ids, topics)
    print(f"\n  Best:       threshold={best[0]}  ARI={best[1]['ari']:.2f}  "
          f"NMI={best[1]['nmi']:.2f}  clusters={best[1]['clusters']}  "
          f"(true topics={n_topics})")
    print(f"  Configured: threshold={cfg_th}  ARI={cfg['ari']:.2f}  "
          f"NMI={cfg['nmi']:.2f}  clusters={cfg['clusters']}")

    # ── LLM, default settings, several runs ─────────────────────────────
    print(f"\nLLM — {LLM_RUNS} runs (default settings):")
    texts_by_id = dict(zip(ids, texts))
    aris, nmis = [], []
    for r in range(LLM_RUNS):
        res = run_llm_scored(ids, vecs, texts_by_id, topics, f"run {r + 1}")
        if res:
            aris.append(res[0])
            nmis.append(res[1])

    # ── LLM scale path: force chunk-then-merge ──────────────────────────
    # Only meaningful if there are enough distinct queries to split into chunks.
    chunk_res = None
    if distinct >= 40:
        forced = max(20, distinct // 3)  # small enough to force multiple chunks
        print(f"\nLLM — chunk-then-merge scale path (forcing max_items={forced}):")
        original = settings.CLUSTERING_LLM_MAX_ITEMS
        settings.CLUSTERING_LLM_MAX_ITEMS = forced
        try:
            chunk_res = run_llm_scored(ids, vecs, texts_by_id, topics, "chunked")
        finally:
            settings.CLUSTERING_LLM_MAX_ITEMS = original

    # ── Summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print(f"SUMMARY  (n={n}, true topics={n_topics})")
    print("=" * 50)
    print(f"  Agglomerative (configured {cfg_th}): ARI={cfg['ari']:.2f}  NMI={cfg['nmi']:.2f}")
    print(f"  Agglomerative (best {best[0]}):        ARI={best[1]['ari']:.2f}  NMI={best[1]['nmi']:.2f}")
    if aris:
        print(f"  LLM (mean of {len(aris)}):               "
              f"ARI={np.mean(aris):.2f}±{np.std(aris):.2f}  "
              f"NMI={np.mean(nmis):.2f}±{np.std(nmis):.2f}")
    if chunk_res:
        print(f"  LLM (chunk-then-merge):            ARI={chunk_res[0]:.2f}  NMI={chunk_res[1]:.2f}")
    print()


if __name__ == "__main__":
    main()
