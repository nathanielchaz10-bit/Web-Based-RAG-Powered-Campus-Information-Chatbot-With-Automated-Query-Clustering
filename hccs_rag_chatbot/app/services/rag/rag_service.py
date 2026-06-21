"""RAG service: thin wrapper around rag_engine.py (same package).

Keeps rag_engine.py as the single source of truth for the retrieval chain
(ChromaDB + Gemini, history-aware). The chain is expensive to build (it embeds
the document corpus on first run), so it is built once and cached for the
lifetime of the process.
"""

import os
import time

import app.services._engine_bootstrap  # noqa: F401  (side effect: bridges GOOGLE_API_KEY)

_rag_chain = None


def get_rag_chain():
    """Lazily build (or load) the cached retrieval chain.

    Raises whatever rag_engine raises if the corpus/API key is missing —
    callers should surface that as a 503.
    """
    global _rag_chain
    if _rag_chain is None:
        from app.services.rag.rag_engine import run_rag_pipeline
        _rag_chain = run_rag_pipeline()
    return _rag_chain


def is_ready() -> bool:
    """Whether the chain has already been built (used for health reporting)."""
    return _rag_chain is not None


def reset_chain() -> None:
    """Drop the cached chain so the next query rebuilds it from disk.

    Called after the corpus changes (a document is indexed or removed) so the
    chat path reloads the Chroma collection and sees the new/removed chunks
    without a process restart.
    """
    global _rag_chain
    _rag_chain = None


def _extract_sources(context_docs) -> list[str]:
    """Turn retrieved chunk metadata into a clean, de-duplicated source list."""
    sources = set()
    for doc in context_docs or []:
        src = (getattr(doc, "metadata", {}) or {}).get("source", "")
        if src:
            name = os.path.splitext(os.path.basename(src))[0]
            name = name.replace("_", " ").replace("-", " ").title()
            sources.add(name)
    return sorted(sources)


def answer_query(question: str, chat_history: list[tuple[str, str]] | None = None) -> dict:
    """Answer one question.

    Args:
        question: the user's message.
        chat_history: list of (role, content) where role is "human" or "ai",
            oldest first. Used to make the retriever conversation-aware.

    Returns dict: answer, sources, response_time_ms, num_context_docs.
    """
    chain = get_rag_chain()
    formatted_history = list(chat_history or [])

    start = time.perf_counter()
    results = chain.invoke({"input": question, "chat_history": formatted_history})
    response_time_ms = int((time.perf_counter() - start) * 1000)

    answer = results.get("answer", "")
    context_docs = results.get("context", [])

    # The history-aware chain rewrites follow-ups into a self-contained
    # question; surface it so the caller can log it for clustering. Falls back
    # to the original question for first turns (no rewrite happened).
    resolved_question = (results.get("standalone_question") or question).strip()

    return {
        "answer": answer,
        "sources": _extract_sources(context_docs),
        "response_time_ms": response_time_ms,
        "num_context_docs": len(context_docs),
        "resolved_question": resolved_question,
    }
