"""Shared text chunking + cleaning for the RAG corpus.

Single source of truth used by BOTH the full pipeline build
(rag_engine.run_rag_pipeline) and the incremental indexer (indexer.py), so a
document chunked at upload time is split and cleaned identically to one chunked
during a from-scratch rebuild -- their vectors land in the same space.
"""

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

# Chunks with fewer than this many *alphanumeric* characters after cleaning are
# dropped as formatting garbage. Counting letters/digits (not total length) is
# deliberate: a Markdown table-separator row like "| :---------- | :--- |" is
# long but carries no meaning, and a mangled PDF/OCR export can emit a line of
# thousands of dashes that the splitter explodes into hundreds of such chunks.
# Left in the index those degenerate vectors rank highly for many queries and
# crowd real answers out of the top-k, so retrieval dead-ends in a fallback.
_MIN_CHUNK_CHARS = 15


def clean_chunk_text(text: str) -> str:
    """Strip hidden Word/OCR artifacts (null bytes, non-breaking spaces) and
    normalize whitespace WITHOUT destroying line structure.

    Horizontal whitespace (spaces/tabs) is collapsed to a single space, but
    newlines are preserved so structured content survives chunking: a Markdown
    table stays one row per line and the OCR cleanup's "CODE — value" lines stay
    one per line, which an LLM reads far better than a single mashed-together
    line. Runs of blank lines are capped at one. (Splitting happens before this
    in chunk_and_clean, so this is purely a content tidy-up -- it doesn't move
    chunk boundaries.)

    Runs of 4+ rule characters (- = _) are collapsed to three: a legit Markdown
    separator ("| :--- |") is untouched in meaning, but a pathological OCR
    dash-line stops bloating whatever chunk it lands in.
    """
    text = (text or "").replace("\x00", "").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # normalize line endings
    text = re.sub(r"([-=_])\1{3,}", r"\1\1\1", text)  # collapse long rule runs
    text = re.sub(r"[^\S\n]+", " ", text)   # collapse spaces/tabs, keep newlines
    text = re.sub(r" *\n *", "\n", text)     # trim spaces hugging newlines
    text = re.sub(r"\n{3,}", "\n\n", text)   # cap blank-line runs at one
    return text.strip()


def chunk_and_clean(documents, min_chars: int = _MIN_CHUNK_CHARS):
    """Split LangChain documents into cleaned chunks.

    Returns the list of chunk Documents with cleaned page_content, dropping any
    chunk left with fewer than ``min_chars`` alphanumeric characters (see
    _MIN_CHUNK_CHARS -- separator-only rows carry no meaning and pollute retrieval).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )
    cleaned = []
    for split in splitter.split_documents(documents):
        text = clean_chunk_text(split.page_content)
        if sum(c.isalnum() for c in text) >= min_chars:
            split.page_content = text
            cleaned.append(split)
    return cleaned
