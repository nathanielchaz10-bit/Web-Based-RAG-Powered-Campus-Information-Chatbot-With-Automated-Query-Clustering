# app/services/clustering/labeler.py
"""
Generates a human-readable label, description, and keyword list for each
cluster produced by algorithm.py. Matches "Generate Metadata and Keywords"
in the SOP2 flowchart.

Uses the Gemini LLM (not TF-IDF) so labels reflect student *intent* rather
than just shared keywords — e.g. a cluster of "how much is tuition" / "can I
pay in installments" / "my payment didn't go through" gets named "Payment
Inquiries" instead of something keyword-literal like "Tuition Payment Pay".
"""
import json
import re
import time
from typing import Dict, List, Optional, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings


class ClusterLabel(TypedDict):
    name: str
    description: str
    keywords: List[str]  # each entry: {"keyword": str, "relevance_score": float}


_FALLBACK_LABEL: ClusterLabel = {
    "name": "Unlabeled Cluster",
    "description": "Automatically generated cluster; the AI labeler did not return a usable result for this group.",
    "keywords": [],
}

_MAX_RETRIES = 3


def _build_prompt(cluster_texts: Dict[int, List[str]]) -> str:
    sections = []
    for label, texts in cluster_texts.items():
        # Cap how many example queries are shown per cluster to keep the
        # prompt small for clusters with hundreds of near-identical questions
        # -- a representative sample is enough for the LLM to name the topic.
        sample = texts[:25]
        numbered = "\n".join(f"    - {t}" for t in sample)
        sections.append(f"Cluster {label} ({len(texts)} total queries):\n{numbered}")

    joined = "\n\n".join(sections)

    return (
        "You are labeling groups of questions that students asked a campus "
        "information chatbot, for a school administrator's analytics "
        "dashboard.\n\n"
        f"{joined}\n\n"
        "For EACH cluster listed above, provide:\n"
        "- name: a short, professional 2-4 word category name (e.g. "
        "'Payment Inquiries', 'Enrollment Process', 'Campus Facilities')\n"
        "- description: one sentence summarizing what students in this "
        "cluster are asking about\n"
        "- keywords: 3-6 representative keywords or short phrases actually "
        "reflected in the sample queries, each with a relevance_score from "
        "0.0 to 1.0 indicating how central that keyword is to the cluster\n\n"
        "Reply with ONLY valid JSON, no markdown, in exactly this format:\n"
        '{"<cluster_label>": {"name": "...", "description": "...", '
        '"keywords": [{"keyword": "...", "relevance_score": 0.9}, ...]}, ...}\n'
        "Use the same cluster numbers given above as the JSON keys (as strings)."
    )


def _coerce_entry(entry) -> Optional[ClusterLabel]:
    """Turn one parsed JSON object into a ClusterLabel, or None if unusable."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    description = str(entry.get("description", "")).strip()
    raw_keywords = entry.get("keywords", [])

    keywords = []
    if isinstance(raw_keywords, list):
        for kw in raw_keywords:
            if isinstance(kw, dict) and kw.get("keyword"):
                try:
                    score = float(kw.get("relevance_score", 0.5))
                except (TypeError, ValueError):
                    score = 0.5
                keywords.append({
                    "keyword": str(kw["keyword"]).strip(),
                    "relevance_score": max(0.0, min(1.0, score)),
                })

    return {
        "name": name,
        "description": description or f"Cluster of {name.lower()} related queries.",
        "keywords": keywords,
    }


def _parse_response(raw: str, expected_labels: List[int]) -> Dict[int, ClusterLabel]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    parsed = json.loads(cleaned)

    # Preferred path: the model echoed our cluster numbers back as JSON keys.
    result: Dict[int, ClusterLabel] = {}
    if isinstance(parsed, dict):
        for label in expected_labels:
            coerced = _coerce_entry(parsed.get(str(label)))
            if coerced:
                result[label] = coerced
    if result:
        return result

    # Fallback: the model renumbered or renamed the keys (common — it likes to
    # use 0,1,2.. or the topic names regardless of the numbers we gave). If the
    # entry count lines up, map them onto our labels positionally, since the
    # clusters are presented to the model in expected_labels order. A possibly
    # mis-ordered name beats every cluster collapsing to "Unlabeled Cluster".
    if isinstance(parsed, dict):
        entries = list(parsed.values())
    elif isinstance(parsed, list):
        entries = parsed
    else:
        entries = []

    if len(entries) == len(expected_labels):
        for label, entry in zip(expected_labels, entries):
            coerced = _coerce_entry(entry)
            if coerced:
                result[label] = coerced

    return result


def label_clusters(groups: Dict[int, List[int]], texts_by_query_id: Dict[int, str]) -> Dict[int, ClusterLabel]:
    """
    Calls Gemini once for the whole batch of clusters (cheaper and gives the
    LLM cross-cluster context to avoid near-duplicate names) and returns a
    label/description/keywords dict per cluster.

    Args:
        groups: cluster label -> list of query_ids (output of algorithm.py).
        texts_by_query_id: query_id -> original query_text.

    Returns:
        Dict mapping the same cluster labels to a ClusterLabel. Any cluster
        the LLM fails to label after retries gets _FALLBACK_LABEL rather than
        being silently dropped — a cluster with a placeholder name is far
        better for the admin dashboard than a cluster that vanishes.
    """
    if not groups:
        return {}

    cluster_texts = {
        label: [texts_by_query_id[qid] for qid in qids if qid in texts_by_query_id]
        for label, qids in groups.items()
    }

    prompt = _build_prompt(cluster_texts)
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)

    labels: Dict[int, ClusterLabel] = {}
    for attempt in range(_MAX_RETRIES):
        try:
            raw = llm.invoke(prompt).content
            labels = _parse_response(raw, list(groups.keys()))
            if labels:
                break
            print(f"[clustering labeler] LLM returned no usable labels. Retrying. (Attempt {attempt + 1}/{_MAX_RETRIES})")
        except json.JSONDecodeError:
            print(f"[clustering labeler] Could not parse LLM response as JSON. Retrying. (Attempt {attempt + 1}/{_MAX_RETRIES})")
        except Exception as exc:
            print(f"[clustering labeler] API error: {exc!r}. Retrying in 10s. (Attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(10)

    # Fill in any cluster the LLM didn't return a label for (partial failure)
    # so every cluster in `groups` always gets *something* back.
    for label in groups:
        if label not in labels:
            labels[label] = dict(_FALLBACK_LABEL)

    return labels