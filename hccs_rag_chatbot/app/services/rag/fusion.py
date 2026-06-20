"""RAG-Fusion building blocks (deliberately dependency-light).

This module holds the parts of RAG-Fusion that don't need the LLM/embedding
stack so they can be reasoned about and unit-tested in isolation:

  * parse_search_queries -- turn the query-generation LLM's raw text into a
    clean list of queries.
  * reciprocal_rank_fusion -- merge several ranked document lists into one.
  * RagFusionChain -- orchestrates generate -> retrieve-each -> RRF -> answer.
    It only ever calls methods on objects handed to it (the generation chain,
    the retriever, the answer chain), so it imports nothing heavy itself.

Design notes specific to this project:
  * ONE LLM call does history-resolution + Taglish->English normalization +
    query expansion together, so the fusion path costs the same number of
    (scarce) Flash calls as the old path while fanning out only on the cheap,
    high-quota embedding side.
  * The generation call fully completes before any embedding request, matching
    the discipline in HistoryAwareRagChain that avoids the Gemini
    embed-immediately-after-flash 500 INTERNAL interaction.
"""

import re
from typing import List, Sequence, Tuple

# A retrieved "document" only needs a .page_content str and a .metadata dict for
# our purposes; we avoid importing langchain's Document type to stay light.

_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def parse_search_queries(raw: str, fallback: str | None = None) -> List[str]:
    """Parse the query-generation LLM output into a clean, ordered, de-duped
    list of queries.

    Handles the usual LLM formatting noise: numbered lists ("1." / "1)"),
    bullets (-, *, •), blank lines, and surrounding whitespace. Order is
    preserved (the first query is treated as the canonical standalone
    elsewhere). If nothing usable is parsed, returns [fallback] when given.
    """
    queries: List[str] = []
    seen = set()
    for line in (raw or "").splitlines():
        line = _LIST_MARKER.sub("", line.strip()).strip()
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(line)

    if not queries and fallback:
        return [fallback.strip()] if fallback.strip() else []
    return queries


def reciprocal_rank_fusion(ranked_lists: Sequence[Sequence], k: int = 60) -> List[Tuple[object, float]]:
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    Merges several independently-ranked document lists into one. A document's
    fused score is the sum over the lists it appears in of 1 / (k + rank),
    where rank is its 0-based position in that list. Documents ranked highly by
    *several* queries therefore rise to the top, while one-off matches sink.
    k (default 60) dampens the influence of top ranks so lower-ranked but
    broadly-agreed-upon documents still count.

    Dedupes on chunk text (page_content). Returns (document, score) pairs
    sorted by descending score.
    """
    scores: dict = {}
    first_seen: dict = {}
    for docs in ranked_lists:
        for rank, doc in enumerate(docs):
            key = getattr(doc, "page_content", None) or repr(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(key, doc)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(first_seen[key], score) for key, score in ranked]


class RagFusionChain:
    """History- and Taglish-aware RAG-Fusion retrieval chain.

    Flow per turn:
      1. generate_queries (ONE Flash call): given chat history + the latest
         question (possibly Tagalog/Taglish, possibly a follow-up), produce N
         standalone ENGLISH search queries. This single call resolves history,
         normalizes language, and expands phrasings at once.
      2. retrieve each query independently (embedding-only; the LLM call above
         has fully returned, so we never embed straight after a Flash call).
      3. reciprocal_rank_fusion to merge the ranked lists.
      4. answer from the fused top-k documents (Flash call #2).

    Returns the same dict shape as the non-fusion path (answer / context /
    standalone_question) so rag_service and the chat endpoint need no changes.
    """

    def __init__(
        self,
        generate_queries,
        retriever,
        question_answer_chain,
        num_queries: int = 4,
        rrf_k: int = 60,
        top_k: int = 5,
    ):
        self._generate = generate_queries
        self._retriever = retriever
        self._qa = question_answer_chain
        self._num_queries = num_queries
        self._rrf_k = rrf_k
        self._top_k = top_k

    def invoke(self, payload, *args, **kwargs):
        question = payload["input"]
        history = payload.get("chat_history") or []

        # 1. One LLM call: resolve + normalize + expand into N English queries.
        raw = self._generate.invoke({"input": question, "chat_history": history})
        queries = parse_search_queries(raw, fallback=question)
        if not queries:
            queries = [question]
        # The first query is the canonical standalone -- used as the QA input
        # and persisted (via rag_service) as the clustering-friendly question.
        standalone = queries[0]

        # 2. Retrieve per query (cheap, high-quota embedding side). A single
        #    sub-query failing must not sink the whole turn.
        ranked_lists: List[list] = []
        for q in queries:
            try:
                ranked_lists.append(list(self._retriever.invoke(q)))
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[rag-fusion] retrieval failed for sub-query {q!r}: {exc!r}")

        # 3. Fuse.
        fused = reciprocal_rank_fusion(ranked_lists, k=self._rrf_k)
        context_docs = [doc for doc, _score in fused[: self._top_k]]

        # 4. Answer from fused context.
        answer = self._qa.invoke(
            {"input": standalone, "chat_history": history, "context": context_docs}
        )

        return {
            "input": question,
            "chat_history": history,
            "context": context_docs,
            "answer": answer,
            "standalone_question": standalone,
        }
