# Archived: LLM clustering experiment

This folder holds an **evaluated-and-rejected** alternative to the query
clustering used by the app. The running system uses **agglomerative clustering**
(`hccs_rag_chatbot/app/services/clustering/`); this LLM-based approach was
benchmarked against it and archived.

## Why it was archived

A bake-off scored both methods against labeled ground truth (Adjusted Rand
Index / Normalized Mutual Information):

| Dataset | Agglomerative (tuned) | LLM | Notes |
|---|---|---|---|
| Small (60 queries, 8 topics) | ARI 0.63 | **ARI 1.00** | LLM looked far better |
| Large (494 queries, 16 topics) | **ARI 0.54** (deterministic) | ARI 0.48 ±0.10 | LLM no better, unstable |
| Large, chunk-then-merge (5 runs) | — | ARI 0.53 ±0.05 | best LLM config; still non-deterministic |

The LLM's apparent advantage was an artifact of the small, easy dataset. At
realistic scale it offered **no quality gain** and was **not reproducible**
(cluster counts swung from 5 to 18 across runs on identical input), so the
deterministic agglomerative method was kept.

## Files

- `algorithm_llm.py` — the LLM grouping method (dedup + intent grouping +
  chunk-then-merge scale path). Was wired into the pipeline behind a config
  flag; that flag and dispatch have been removed.
- `eval_dataset.py` — hand-authored ~500 labeled queries (16 topics + noise),
  deliberately not LLM-generated, used as ground truth.
- `bakeoff.py` — scores both methods on the seeded 60-query set.
- `bakeoff_large.py` — scores both on the ~500-query set; caches embeddings.
- `verify_chunked.py` — reruns the LLM chunk-then-merge config to measure its
  run-to-run stability.

## Running these again

They still import the live app (`app.*`) for embeddings/config, so run them with
the project's virtualenv active and a `GEMINI_API_KEY` set:

```bash
cd archive/llm_clustering_experiment
python bakeoff_large.py     # embeds once, caches to this folder, then scores
python verify_chunked.py    # reuses the cache; LLM calls only
```

The settings they read (`CLUSTERING_DEDUP_THRESHOLD`, `CLUSTERING_LLM_MAX_ITEMS`)
still exist in `app/core/config.py` for this purpose.
