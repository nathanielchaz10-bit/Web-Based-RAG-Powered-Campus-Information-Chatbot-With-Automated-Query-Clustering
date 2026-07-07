"""RAG service: thin wrapper around rag_engine.py (same package).

Keeps rag_engine.py as the single source of truth for the retrieval chain
(ChromaDB + Gemini, history-aware). The chain is expensive to build (it embeds
the document corpus on first run), so it is built once and cached for the
lifetime of the process.
"""

import os
import time

import app.services._engine_bootstrap  # noqa: F401  (side effect: bridges GOOGLE_API_KEY)
from app.core.config import settings

_rag_chain = None
# Guest path caches: a stuff-documents QA chain (corpus-independent) and the
# vector store handle (dropped on reset_chain() so re-indexing is picked up).
_guest_answer_chain = None
_guest_vectorstore = None


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
    global _rag_chain, _guest_vectorstore
    _rag_chain = None
    _guest_vectorstore = None


def _extract_sources(context_docs) -> list[str]:
    """Cite just the single most relevant source: the document behind the
    top-ranked retrieved chunk.

    context_docs arrives ordered by relevance (RRF score in the fusion path,
    similarity in the guest/non-fusion paths), so the first chunk that carries a
    source is the primary one. A simple question shouldn't show a pile of
    documents. (Full retrieval is still logged via retrieved_document_ids, so
    document-usage analytics are unaffected.)
    """
    for doc in context_docs or []:
        src = (getattr(doc, "metadata", {}) or {}).get("source", "")
        if src:
            name = os.path.splitext(os.path.basename(src))[0]
            return [name.replace("_", " ").replace("-", " ").title()]
    return []


def _retrieved_document_ids(context_docs) -> list[int]:
    """Distinct document_ids among the retrieved chunks.

    Chunks indexed via the admin uploader carry their owning document_id in
    metadata (see rag.indexer); the chat endpoint uses these to log a usage
    event per document per answered query. Chunks without a document_id (e.g.
    a from-scratch folder build) are simply skipped.
    """
    ids = set()
    for doc in context_docs or []:
        did = (getattr(doc, "metadata", {}) or {}).get("document_id")
        if did is None:
            continue
        try:
            ids.add(int(did))
        except (TypeError, ValueError):
            continue
    return sorted(ids)


def answer_query(question: str, chat_history: list[tuple[str, str]] | None = None) -> dict:
    """Answer one question.

    Args:
        question: the user's message.
        chat_history: list of (role, content) where role is "human" or "ai",
            oldest first. Used to make the retriever conversation-aware.

    Returns dict: answer, is_fallback, sources, retrieved_document_ids,
    response_time_ms, num_context_docs, resolved_question.
    """
    chain = get_rag_chain()
    formatted_history = list(chat_history or [])

    start = time.perf_counter()
    results = chain.invoke({"input": question, "chat_history": formatted_history})
    response_time_ms = int((time.perf_counter() - start) * 1000)

    answer = results.get("answer", "")
    context_docs = results.get("context", [])

    # If the model emitted the can't-answer sentinel, swap in a friendly message
    # for the student and flag it, so the dashboard can count answerability
    # exactly instead of string-matching the output text. (Imported here rather
    # than at module top to preserve the lazy rag_engine import.)
    from app.services.rag.rag_engine import FALLBACK_MESSAGE, is_no_answer
    is_fallback = is_no_answer(answer)
    if is_fallback:
        answer = FALLBACK_MESSAGE

    # The history-aware chain rewrites follow-ups into a self-contained
    # question; surface it so the caller can log it for clustering. Falls back
    # to the original question for first turns (no rewrite happened).
    resolved_question = (results.get("standalone_question") or question).strip()

    return {
        "answer": answer,
        "is_fallback": is_fallback,
        # On a non-answer, cite nothing and log no document "usage" -- no source
        # actually helped, so showing citations or counting a retrieval would be
        # misleading.
        "sources": [] if is_fallback else _extract_sources(context_docs),
        "retrieved_document_ids": [] if is_fallback else _retrieved_document_ids(context_docs),
        "response_time_ms": response_time_ms,
        "num_context_docs": len(context_docs),
        "resolved_question": resolved_question,
    }


def _get_guest_answer_chain():
    global _guest_answer_chain
    if _guest_answer_chain is None:
        from app.services.rag.rag_engine import build_answer_chain, build_llm
        _guest_answer_chain = build_answer_chain(build_llm())
    return _guest_answer_chain


def _get_guest_vectorstore():
    global _guest_vectorstore
    if _guest_vectorstore is None:
        from app.services.rag.indexer import get_vectorstore
        _guest_vectorstore = get_vectorstore()
    return _guest_vectorstore


def answer_query_restricted(question: str, allowed_document_ids) -> dict:
    """Answer a guest question using ONLY chunks from ``allowed_document_ids``.

    Stateless (no chat history) single-query retrieval with a Chroma metadata
    filter on document_id, then the same QA prompt/NO_ANSWER sentinel the
    authenticated path uses. Returns the same shape as ``answer_query`` minus the
    resolved-question field.

    ponytail: single-query retrieval, no RAG-Fusion/history rewrite -- guests are
    anonymous and one-shot, so the extra Gemini calls those add aren't worth it.
    """
    from app.services.rag.rag_engine import GUEST_FALLBACK_MESSAGE, is_no_answer

    ids = [int(i) for i in (allowed_document_ids or [])]
    if not ids:
        # No guest-visible documents configured/active -> nothing to answer from.
        return {
            "answer": GUEST_FALLBACK_MESSAGE, "is_fallback": True, "sources": [],
            "retrieved_document_ids": [], "response_time_ms": 0, "num_context_docs": 0,
        }

    start = time.perf_counter()
    context_docs = _get_guest_vectorstore().similarity_search(
        question,
        k=settings.TOP_K_CHUNKS,
        filter={"document_id": {"$in": ids}},
    )
    answer = _get_guest_answer_chain().invoke(
        {"input": question, "chat_history": [], "context": context_docs}
    )
    response_time_ms = int((time.perf_counter() - start) * 1000)

    is_fallback = is_no_answer(answer)
    if is_fallback:
        answer = GUEST_FALLBACK_MESSAGE

    return {
        "answer": answer,
        "is_fallback": is_fallback,
        "sources": [] if is_fallback else _extract_sources(context_docs),
        "retrieved_document_ids": [] if is_fallback else _retrieved_document_ids(context_docs),
        "response_time_ms": response_time_ms,
        "num_context_docs": len(context_docs),
    }
