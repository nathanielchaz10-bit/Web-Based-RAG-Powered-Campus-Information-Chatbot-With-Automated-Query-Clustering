"""
Bake-off: agglomerative vs LLM clustering, scored against the seeded
ground-truth topics.

The seed script (database/seed_queries.py) groups its sample questions by topic
(8 real topics + a "_noise" tail of unrelated one-offs), so we have a labeled
ground truth. This script:

  1. Reloads the embeddings cached in query_logs.query_vector (no re-embedding)
     and matches each seeded query back to its true topic.
  2. Runs BOTH clustering methods on the same vectors.
  3. Scores each against the ground truth with Adjusted Rand Index (ARI) and
     Normalized Mutual Information (NMI) -- standard external cluster-quality
     metrics where 1.0 = perfect agreement with the true topics.
  4. Sweeps the agglomerative threshold to report its best achievable score,
     and runs the LLM method several times to measure its run-to-run variance.

Scoring is done on the 8 real topics only; how each method handled the noise
tail (correct = left unclustered) is reported separately.

Run from inside hccs_rag_chatbot/:
    python bakeoff.py

Needs a prior clustering run (so embeddings are cached) and, for the LLM method,
a working GEMINI_API_KEY. Read-only: never writes to the database.
"""
import json
import os
import sys
from contextlib import redirect_stdout

import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Bridge GEMINI_API_KEY -> GOOGLE_API_KEY for the LLM method (same as pipeline).
import app.services._engine_bootstrap  # noqa: F401

from app.core.database import SessionLocal
import app.models  # noqa: F401  registers ORM models
from app.models.query_log import QueryLog
from app.core.config import settings
from app.services.clustering.algorithm import run_agglomerative_clustering
from app.services.clustering.algorithm_llm import run_llm_clustering
from database.seed_queries import SAMPLE_QUERIES

NOISE_TOPIC = "_noise"
LLM_RUNS = 3
SWEEP = [round(x, 3) for x in np.arange(0.05, 0.45, 0.025)]


def load():
    """Return (ids, texts, vectors, true_topics) for seeded, embedded queries."""
    truth = {q: topic for topic, qs in SAMPLE_QUERIES.items() for q in qs}

    db = SessionLocal()
    try:
        rows = (
            db.query(QueryLog.query_id, QueryLog.query_text, QueryLog.query_vector)
            .filter(QueryLog.is_valid.is_(True))
            .filter(QueryLog.query_vector.isnot(None))
            .all()
        )
    finally:
        db.close()

    ids, texts, vecs, topics = [], [], [], []
    for qid, text, raw in rows:
        if text not in truth:
            continue  # only score the known seeded set
        try:
            v = json.loads(raw)
        except (TypeError, ValueError):
            continue
        ids.append(qid)
        texts.append(text)
        vecs.append(v)
        topics.append(truth[text])
    return ids, texts, np.array(vecs), topics


def groups_to_pred(groups, ids):
    """Per-query predicted labels; queries dropped as noise become singletons."""
    qid_to_label = {}
    for label, qids in groups.items():
        for q in qids:
            qid_to_label[q] = label
    pred, singleton = [], -1
    for qid in ids:
        if qid in qid_to_label:
            pred.append(qid_to_label[qid])
        else:
            pred.append(singleton)
            singleton -= 1
    return pred


def score(groups, ids, topics):
    """ARI/NMI on the 8 real topics + how the noise tail was handled."""
    pred = groups_to_pred(groups, ids)

    keep = [i for i, t in enumerate(topics) if t != NOISE_TOPIC]
    true_k = [topics[i] for i in keep]
    pred_k = [pred[i] for i in keep]
    ari = adjusted_rand_score(true_k, pred_k)
    nmi = normalized_mutual_info_score(true_k, pred_k)

    noise = [i for i, t in enumerate(topics) if t == NOISE_TOPIC]
    noise_left_unclustered = sum(1 for i in noise if pred[i] < 0)

    clustered = sum(len(v) for v in groups.values())
    return {
        "ari": ari,
        "nmi": nmi,
        "clusters": len(groups),
        "coverage": clustered / len(ids) if ids else 0,
        "noise_correct": noise_left_unclustered,
        "noise_total": len(noise),
    }


def agglomerative_at(threshold, ids, vecs):
    """Run the real agglomerative function at a given threshold (quietly)."""
    original = settings.CLUSTERING_DISTANCE_THRESHOLD
    settings.CLUSTERING_DISTANCE_THRESHOLD = threshold
    try:
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            return run_agglomerative_clustering(ids, vecs)
    finally:
        settings.CLUSTERING_DISTANCE_THRESHOLD = original


def main():
    ids, texts, vecs, topics = load()
    n = len(ids)
    n_topics = len({t for t in topics if t != NOISE_TOPIC})
    n_noise = sum(1 for t in topics if t == NOISE_TOPIC)

    if n < settings.CLUSTERING_MIN_CLUSTER_SIZE:
        print(
            f"Only {n} seeded+embedded queries found. Seed the data and run "
            "clustering once so embeddings are cached, then retry."
        )
        return

    print(f"\nGround truth: {n_topics} topics across {n - n_noise} queries "
          f"(+ {n_noise} noise queries). dim={vecs.shape[1]}\n")

    # ── Agglomerative: sweep to find its best achievable score ──────────
    print("AGGLOMERATIVE — threshold sweep (scored vs ground truth):")
    print(f"{'threshold':>9} | {'clusters':>8} | {'ARI':>5} | {'NMI':>5} | {'coverage':>8}")
    print("-" * 50)
    best = None
    for th in SWEEP:
        s = score(agglomerative_at(th, ids, vecs), ids, topics)
        print(f"{th:>9.3f} | {s['clusters']:>8} | {s['ari']:>5.2f} | "
              f"{s['nmi']:>5.2f} | {s['coverage']:>7.0%}")
        if best is None or s["ari"] > best[1]["ari"]:
            best = (th, s)

    cfg_th = settings.CLUSTERING_DISTANCE_THRESHOLD
    cfg = score(agglomerative_at(cfg_th, ids, vecs), ids, topics)
    print(f"\n  Best:       threshold={best[0]}  ARI={best[1]['ari']:.2f}  "
          f"NMI={best[1]['nmi']:.2f}  clusters={best[1]['clusters']}")
    print(f"  Configured: threshold={cfg_th}  ARI={cfg['ari']:.2f}  "
          f"NMI={cfg['nmi']:.2f}  clusters={cfg['clusters']}  "
          f"noise left unclustered={cfg['noise_correct']}/{cfg['noise_total']}")

    # ── LLM: run several times to measure variance ──────────────────────
    print(f"\nLLM — {LLM_RUNS} runs (non-deterministic):")
    texts_by_id = dict(zip(ids, texts))
    aris, nmis = [], []
    ran = 0
    for r in range(LLM_RUNS):
        try:
            with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
                groups = run_llm_clustering(ids, vecs, texts_by_id)
        except Exception as exc:
            print(f"  run {r + 1}: FAILED ({exc}). Check GEMINI_API_KEY / quota.")
            continue
        s = score(groups, ids, topics)
        aris.append(s["ari"])
        nmis.append(s["nmi"])
        ran += 1
        print(f"  run {r + 1}: clusters={s['clusters']}  ARI={s['ari']:.2f}  "
              f"NMI={s['nmi']:.2f}  coverage={s['coverage']:.0%}  "
              f"noise left unclustered={s['noise_correct']}/{s['noise_total']}")

    # ── Verdict ─────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  Agglomerative (configured {cfg_th}): ARI={cfg['ari']:.2f}  NMI={cfg['nmi']:.2f}")
    print(f"  Agglomerative (best {best[0]}):        ARI={best[1]['ari']:.2f}  NMI={best[1]['nmi']:.2f}")
    if ran:
        print(f"  LLM (mean of {ran}):                 "
              f"ARI={np.mean(aris):.2f}±{np.std(aris):.2f}  "
              f"NMI={np.mean(nmis):.2f}±{np.std(nmis):.2f}")
        winner = "LLM" if np.mean(aris) > best[1]["ari"] else "Agglomerative (tuned)"
        print(f"\n  Higher ARI: {winner}. Remember the LLM's ± is its "
              "run-to-run instability — weigh that against any quality edge.")
    else:
        print("  LLM: no successful runs (see errors above).")
    print()


if __name__ == "__main__":
    main()
