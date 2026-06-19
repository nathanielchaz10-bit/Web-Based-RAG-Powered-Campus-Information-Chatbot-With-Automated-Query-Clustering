# Patch Notes — `test/clustering-methods`

_Last updated: 2026-06-19_

These notes cover the clustering changes made on this branch (since the PR #6
merge). The focus of the branch: **decide the clustering method, fix the
over-fragmentation problem, and make the system maintainable.**

---

## TL;DR

1. **Clustering uses agglomerative only.** An LLM-based alternative was built,
   benchmarked, and **archived** (it was no better at scale and unstable).
2. **Fixed the over-fragmentation bug** (~50 clusters for ~16 topics) by
   **mean-centering** the embeddings before clustering.
3. **The distance threshold is tuned and pinned to `0.85`** (still configurable
   in `.env`), replacing a brittle auto-pick that collapsed to 2 clusters.
4. **Every clustering run now logs diagnostics** to the database.
5. **A monthly self-check** watches the threshold for drift and recommends a
   re-tune when needed (it never changes the value automatically).

---

## 1. Clustering method: agglomerative chosen, LLM experiment archived

We compared two ways of grouping queries:

- **Agglomerative** (scikit-learn) — deterministic, cheap, scales freely.
- **LLM-based** — groups queries by intent using the LLM.

A bake-off scored both against a labeled test set. On a small set the LLM looked
better, but on a realistic ~500-query set it was **no better and not
reproducible** (cluster counts swung wildly between identical runs). So we kept
**agglomerative**.

All the LLM-method code + the evaluation scripts were moved to
**`archive/llm_clustering_experiment/`** (with a README explaining the result
and how to re-run them). Nothing in the running app imports it anymore.

> If a panelist asks "did you consider an LLM approach?" → yes, we built it,
> measured it, and rejected it for cause. See the archive folder.

## 2. The over-fragmentation fix: mean-centering

**Problem:** clustering shattered each topic into many tiny clusters.

**Cause:** Gemini embeddings are *anisotropic* — every embedding shares a big
common component, so all queries look ~80% similar to each other (the tuner
shows raw similarity bunched at ~0.83). No single threshold worked: tight enough
to separate topics split topics apart; loose enough to stop splitting merged
unrelated topics.

**Fix:** subtract the average embedding ("mean-centering") before clustering.
This removes the shared component, so unrelated queries become genuinely
dissimilar (centered similarity spreads out around 0) and topics separate
cleanly. This step also gets **more accurate as more queries accumulate**.

Implemented in `algorithm.py` (`_mean_center`). The clustering, the tuner, and
the health-check all operate on the centered vectors.

## 3. The distance threshold: tuned, pinned to 0.85, configurable

`CLUSTERING_DISTANCE_THRESHOLD` controls how similar two queries must be to group
together. After centering, the useful value sits higher than before.

- **Default is now `0.85`**, tuned on real cached vectors (gives ~8 balanced
  topic clusters at ~82% coverage on the seed data, just below where topics
  start merging into blobs).
- It's a **standard clustering hyperparameter** (like `k` in k-means or `eps` in
  DBSCAN) and is **configurable in `.env`**.
- It is **robust to query volume**: more queries → more/bigger clusters at the
  same threshold, not a wrong threshold.

> We briefly shipped an "auto" mode that picked the threshold from the data each
> run. It was **removed** — it reliably collapsed to 2 clusters because the math
> it used always cuts at the top of the cluster tree. Picking the number of
> clusters fully automatically is a known-unreliable problem, so we use a tuned +
> monitored value instead.

## 4. Tuning tool: `tune_threshold.py`

Run it to (re)choose the threshold against your own cached vectors — **no
re-embedding, no API calls, read-only.**

```bash
cd hccs_rag_chatbot
python tune_threshold.py
```

It prints the raw-vs-centered similarity spread, a sweep table
(threshold → clusters → coverage), and a suggested starting value. You read the
table and pick a value that gives a sensible number of clusters before "blobs"
form, then set it in `.env`.

## 5. Per-run diagnostics (database)

Each clustering run now records extra fields in `clustering_runs.parameters`:

```json
{ "clusters_found": 8, "queries_clustered": 49, "queries_left_unclustered": 11,
  "distance_threshold": 0.85, "min_cluster_size": 3, "raw_groups": 10 }
```

The gap between `raw_groups` (before the min-size filter) and `clusters_found`
shows how much was dropped as noise — i.e. a fragmentation signal you can review
per run.

## 6. Monthly threshold health-check (new)

A scheduled job (1st of each month) checks whether `0.85` is still healthy
against the accumulated data and **records a recommendation for review** — it
**does not** change the value itself.

- Flags **over-fragmenting** (coverage drops too low → threshold too tight) or
  **over-merging** (everything collapses into a blob → too loose), plus drift
  vs the previous check.
- Writes results to the `system_metrics` table (`metric_type =
  "clustering_threshold_check"`) and the logs.
- Cheap: reads cached embeddings only.

Run it on demand:

```bash
cd hccs_rag_chatbot
python -m app.services.clustering.health_check
```

---

## `.env` settings (clustering)

| Setting | Default | Meaning |
|---|---|---|
| `CLUSTERING_DISTANCE_THRESHOLD` | `0.85` | How similar queries must be to group (on centered vectors). Re-tune with `tune_threshold.py`. |
| `CLUSTERING_MIN_CLUSTER_SIZE` | `3` | Smallest group that survives as a cluster. |
| `CLUSTERING_MIN_QUERIES` | `3` | Minimum queries before a run starts. |
| `CLUSTERING_SCHEDULE_HOUR` | `2` | Hour (UTC) for the daily run; monthly health-check runs on the 1st at `:30`. |

**Removed:** `CLUSTERING_METHOD` (no longer switchable — agglomerative only).
`CLUSTERING_DEDUP_THRESHOLD` / `CLUSTERING_LLM_MAX_ITEMS` remain in `config.py`
but are only used by the archived evaluation scripts.

> **Action for everyone:** in your local `.env`, set
> `CLUSTERING_DISTANCE_THRESHOLD=0.85` (or delete the line to use the default),
> and remove any old `CLUSTERING_METHOD` line. Restart uvicorn.

---

## Files changed / added

**Active app:**
- `app/services/clustering/algorithm.py` — mean-centering + threshold handling.
- `app/services/clustering/pipeline.py` — agglomerative-only; logs diagnostics.
- `app/services/clustering/health_check.py` — **new**, monthly drift check.
- `app/services/clustering/scheduler.py` — added the monthly job.
- `app/services/clustering/labeler.py` — more robust to the LLM renumbering
  cluster labels (fixes occasionally-mislabeled clusters).
- `app/core/config.py`, `.env.example` — threshold default + docs; removed
  LLM-method settings from the example.
- `tune_threshold.py` — **new** tuning tool (centered space).

**Archived (not used by the app):**
- `archive/llm_clustering_experiment/` — the LLM method + bake-off / evaluation
  scripts + a README.

---

## Quick reference: how to run things

| Task | Command (from `hccs_rag_chatbot/`) |
|---|---|
| Re-tune the threshold | `python tune_threshold.py` |
| Run the threshold health-check now | `python -m app.services.clustering.health_check` |
| Re-run the archived method bake-off | see `archive/llm_clustering_experiment/README.md` |
