"""
Verify the stability of the LLM chunk-then-merge config.

In bakeoff_large.py the chunked path scored best on a SINGLE run (ARI 0.61, 17
clusters ~ 16 true topics). One run says nothing about reproducibility, which is
the whole concern. This runs that exact config several times on the SAME cached
embeddings (no re-embedding -- only LLM grouping calls) and reports the spread,
so we can see whether the better score is stable or luck.

Run from inside hccs_rag_chatbot/ AFTER bakeoff_large.py has cached embeddings:
    python verify_chunked.py          # default 5 runs
    python verify_chunked.py 8        # custom run count

Needs a working GEMINI_API_KEY.
"""
import os
import sys

import numpy as np
from sklearn.preprocessing import normalize

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import app.services._engine_bootstrap  # noqa: F401

from app.core.config import settings
from app.services.clustering.algorithm_llm import run_llm_clustering, _deduplicate
from eval_dataset import build_dataset
import bakeoff as B
import bakeoff_large as BL


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    data = build_dataset()
    texts = [t for t, _ in data]
    topics = [top for _, top in data]
    ids = list(range(len(texts)))
    texts_by_id = dict(zip(ids, texts))

    vecs = BL.get_embeddings(texts)  # loads from cache if present
    distinct = len(_deduplicate(normalize(vecs), settings.CLUSTERING_DEDUP_THRESHOLD))
    forced = max(20, distinct // 3)  # same value bakeoff_large.py used

    n_topics = len({t for t in topics if t != "_noise"})
    print(f"\nVerifying chunk-then-merge LLM stability: {runs} runs, "
          f"max_items={forced}, distinct={distinct}, true topics={n_topics}.\n")

    aris, nmis, cluster_counts = [], [], []
    original = settings.CLUSTERING_LLM_MAX_ITEMS
    settings.CLUSTERING_LLM_MAX_ITEMS = forced
    try:
        for r in range(runs):
            try:
                with open(os.devnull, "w") as devnull, B.redirect_stdout(devnull):
                    groups = run_llm_clustering(ids, vecs, texts_by_id)
            except Exception as exc:
                print(f"  run {r + 1}: FAILED ({exc})")
                continue
            s = B.score(groups, ids, topics)
            aris.append(s["ari"])
            nmis.append(s["nmi"])
            cluster_counts.append(s["clusters"])
            print(f"  run {r + 1}: clusters={s['clusters']:>3}  "
                  f"ARI={s['ari']:.2f}  NMI={s['nmi']:.2f}  "
                  f"coverage={s['coverage']:.0%}")
    finally:
        settings.CLUSTERING_LLM_MAX_ITEMS = original

    print("\n" + "=" * 50)
    print(f"CHUNKED LLM STABILITY  ({len(aris)} successful runs)")
    print("=" * 50)
    if aris:
        print(f"  ARI: mean={np.mean(aris):.2f}  std={np.std(aris):.2f}  "
              f"min={min(aris):.2f}  max={max(aris):.2f}")
        print(f"  NMI: mean={np.mean(nmis):.2f}  std={np.std(nmis):.2f}")
        print(f"  clusters: {sorted(cluster_counts)}  (true={n_topics})")
        print()
        print("  Compare to:")
        print("    Agglomerative (deterministic): ARI=0.54  NMI=0.82")
        print("    LLM default (3 runs):          ARI=0.48 ±0.10")
        print()
        spread = max(aris) - min(aris)
        if spread <= 0.05:
            print("  -> Tight spread: the chunked config is reproducible in practice.")
        else:
            print(f"  -> ARI spread {spread:.2f}: still meaningfully unstable run-to-run.")
    else:
        print("  No successful runs (check GEMINI_API_KEY / quota).")
    print()


if __name__ == "__main__":
    main()
