# app/services/clustering/algorithm_llm.py
"""
LLM-based grouping strategy (the alternative to algorithm.py's Agglomerative).

Selected when settings.CLUSTERING_METHOD == "llm". Unlike the agglomerative
path, embeddings here are used ONLY to collapse near-duplicate queries; the
actual decision of *which queries form a topic* is made by the LLM, grouping by
student intent rather than embedding proximity. This is what lets payment
phrasings ("how much is tuition", "can I pay in installments", "my payment
failed") land in a single "Payment Inquiries" topic instead of being split by
surface wording.

This module is a pure function with NO database access — it returns the same
`Dict[int, List[query_id]]` shape that run_agglomerative_clustering returns, so
pipeline.py can swap between the two without any other change. Cluster *naming*
is still done downstream by labeler.py (shared by both methods); the names the
LLM emits while grouping are discarded here.

Scale: a single LLM prompt holds every distinct query, so once the post-dedup
count exceeds settings.CLUSTERING_LLM_MAX_ITEMS we fall back to a
chunk-then-merge strategy to stay under the model's context window (the
~1k–2k peak this deployment targets can exceed a comfortable single prompt).
"""
import json
import re
import time
from typing import Dict, List

import numpy as np
from langchain_google_genai import ChatGoogleGenerativeAI
from sklearn.preprocessing import normalize

from app.core.config import settings

_MAX_RETRIES = 3


class LLMClusteringError(Exception):
    """Raised when the LLM fails to return any usable grouping after retries.

    pipeline.py catches this (via its broad `except Exception`) and records
    ClusteringRun.status = FAILED_ML, so a transient LLM/API outage is logged
    as a real ML failure rather than being mistaken for a legitimate
    "0 topics found" run.
    """
    pass


def run_llm_clustering(
    query_ids: List[int],
    vectors: np.ndarray,
    texts_by_id: Dict[int, str],
) -> Dict[int, List[int]]:
    """
    Groups queries into topics using the LLM.

    Args:
        query_ids: QueryLog.query_id values, aligned 1:1 with `vectors`.
        vectors: embedding matrix (same order as query_ids), used for dedup.
        texts_by_id: query_id -> original query_text (the LLM sees the text).

    Returns:
        Dict[int, List[query_id]]: contiguous integer cluster label -> member
        query_ids. Groups below settings.CLUSTERING_MIN_QUERIES are dropped as
        noise, matching the agglomerative path's MIN_CLUSTER_SIZE filter.

    Raises:
        LLMClusteringError: if the LLM produced no grouping at all (treated as
        an ML failure by the caller).
    """
    n = len(query_ids)
    if n == 0:
        return {}

    texts = [texts_by_id[qid] for qid in query_ids]
    normed = normalize(np.asarray(vectors))

    # 1. Collapse near-duplicates so the LLM sees each distinct question once.
    #    dup_groups[k] is a list of indices into query_ids; index 0 is the
    #    representative actually shown to the LLM.
    dup_groups = _deduplicate(normed, settings.CLUSTERING_DEDUP_THRESHOLD)
    rep_texts = [texts[g[0]] for g in dup_groups]
    print(
        f"[clustering llm] Deduplicated {n} queries down to "
        f"{len(rep_texts)} distinct ones."
    )

    # 2. Ask the LLM to organize the representatives into intent-based topics.
    #    `named_groups` members are positions into rep_texts / dup_groups.
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)
    if len(rep_texts) <= settings.CLUSTERING_LLM_MAX_ITEMS:
        named_groups = _llm_group(llm, rep_texts)
    else:
        print(
            f"[clustering llm] {len(rep_texts)} distinct queries exceeds "
            f"max {settings.CLUSTERING_LLM_MAX_ITEMS}; using chunk-then-merge."
        )
        named_groups = _llm_group_chunked(llm, rep_texts)

    if not named_groups:
        raise LLMClusteringError(
            "LLM returned no usable grouping after retries."
        )

    # 3. Expand each representative back to all its near-duplicate originals
    #    and re-key as contiguous integer labels, dropping below-minimum noise.
    min_size = settings.CLUSTERING_MIN_CLUSTER_SIZE
    groups: Dict[int, List[int]] = {}
    next_label = 0
    for group in named_groups:
        member_query_ids: List[int] = []
        for rep_pos in group.get("members", []):
            # Ignore hallucinated / out-of-range indices from the model.
            if not isinstance(rep_pos, int) or not (0 <= rep_pos < len(dup_groups)):
                continue
            for original_idx in dup_groups[rep_pos]:
                member_query_ids.append(query_ids[original_idx])

        # De-dup query_ids in case the LLM listed a representative twice.
        member_query_ids = list(dict.fromkeys(member_query_ids))

        if len(member_query_ids) < min_size:
            continue
        groups[next_label] = member_query_ids
        next_label += 1

    return groups


def _deduplicate(normed: np.ndarray, threshold: float) -> List[List[int]]:
    """Greedily group near-duplicate rows by cosine similarity.

    Returns a list of groups, each a list of original row indices, the first of
    which is the group's representative. O(n^2), fine for the hundreds-to-low-
    thousands of queries a campus chatbot realistically accumulates.
    """
    n = len(normed)
    sim = normed @ normed.T
    assigned = [False] * n
    groups: List[List[int]] = []
    for i in range(n):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if not assigned[j] and sim[i, j] >= threshold:
                assigned[j] = True
                group.append(j)
        groups.append(group)
    return groups


def _strip_fences(raw: str) -> str:
    """Remove ```json ... ``` fences some models wrap JSON replies in."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()


def _invoke_json_list(llm, prompt: str, what: str) -> List[dict]:
    """Call the LLM and parse a JSON list reply, retrying transient failures.

    Returns [] only if every attempt failed — callers decide whether an empty
    result is fatal.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            raw = _strip_fences(llm.invoke(prompt).content)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            print(f"[clustering llm] {what}: unexpected JSON shape. Retrying.")
        except json.JSONDecodeError:
            print(
                f"[clustering llm] {what}: could not parse JSON. "
                f"Retrying. (Attempt {attempt + 1}/{_MAX_RETRIES})"
            )
        except Exception as exc:
            print(
                f"[clustering llm] {what}: API error {exc!r}. "
                f"Retrying in 10s. (Attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            time.sleep(10)
    return []


def _llm_group(llm, rep_texts: List[str]) -> List[dict]:
    """Organize representative queries into named topic groups in one prompt.

    Returns a list of {"name": str, "members": [int, ...]} where members are
    positions into rep_texts.
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
    return _invoke_json_list(llm, prompt, "grouping")


def _llm_group_chunked(llm, rep_texts: List[str]) -> List[dict]:
    """Scale path: group each chunk separately, then merge topics across chunks.

    1. Split the representatives into chunks of CLUSTERING_LLM_MAX_ITEMS and
       group each chunk independently (members remapped to global rep positions).
    2. A second LLM pass merges preliminary topics that mean the same thing
       across chunks, so "Payment Inquiries" from chunk 1 and "Tuition Payments"
       from chunk 3 collapse into a single final topic.

    Returns the same {"name", "members": [global rep positions]} shape as
    _llm_group, so the caller is agnostic to which path produced it.
    """
    chunk_size = settings.CLUSTERING_LLM_MAX_ITEMS

    # --- 1. Per-chunk grouping -------------------------------------------
    prelim: List[dict] = []  # each: {"name", "members": [global rep positions]}
    for start in range(0, len(rep_texts), chunk_size):
        chunk_positions = list(range(start, min(start + chunk_size, len(rep_texts))))
        chunk_texts = [rep_texts[p] for p in chunk_positions]
        print(
            f"[clustering llm] Grouping chunk {start}-{start + len(chunk_texts)} "
            f"of {len(rep_texts)}."
        )
        for group in _llm_group(llm, chunk_texts):
            global_members = [
                chunk_positions[m]
                for m in group.get("members", [])
                if isinstance(m, int) and 0 <= m < len(chunk_positions)
            ]
            if global_members:
                prelim.append({
                    "name": str(group.get("name", "")).strip() or "Unnamed",
                    "members": global_members,
                })

    if not prelim:
        return []
    # Only one chunk produced topics, or a single chunk — nothing to merge.
    if len(prelim) == 1:
        return prelim

    # --- 2. Merge preliminary topics across chunks -----------------------
    merged = _llm_merge(llm, [p["name"] for p in prelim])
    if not merged:
        # Merge step failed; degrade gracefully to the un-merged per-chunk
        # topics rather than losing the whole run. Some near-duplicate topic
        # names may remain, which is far better than no clusters at all.
        print("[clustering llm] Merge step failed; keeping per-chunk topics.")
        return prelim

    final: List[dict] = []
    for mg in merged:
        union: List[int] = []
        for pi in mg.get("members", []):
            if isinstance(pi, int) and 0 <= pi < len(prelim):
                union.extend(prelim[pi]["members"])
        if union:
            final.append({
                "name": str(mg.get("name", "")).strip() or "Unnamed",
                "members": list(dict.fromkeys(union)),
            })
    return final or prelim


def _llm_merge(llm, topic_names: List[str]) -> List[dict]:
    """Merge a flat list of preliminary topic names into final topics.

    Returns a list of {"name": str, "members": [int, ...]} where members are
    indices into topic_names. Every input index must appear in exactly one
    output group.
    """
    numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(topic_names))
    prompt = (
        "The following are topic-category names produced by grouping student "
        "questions to a campus chatbot in separate batches. Because they came "
        "from different batches, several names refer to the SAME underlying "
        "topic (e.g. 'Payment Inquiries' and 'Tuition Payments').\n\n"
        "Here is the numbered list of category names:\n"
        f"{numbered}\n\n"
        "Merge the ones that describe the same student intent into a single "
        "category. Every numbered item must appear in exactly one merged "
        "category. Give each merged category a short, professional 2-3 word "
        "name.\n\n"
        "Reply with ONLY valid JSON, no markdown, in exactly this format:\n"
        '[{"name": "Category Name", "members": [0, 4]}, ...]'
    )
    return _invoke_json_list(llm, prompt, "merge")
