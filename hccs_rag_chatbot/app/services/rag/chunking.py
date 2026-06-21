"""Shared text chunking + cleaning for the RAG corpus.

Single source of truth used by BOTH the full pipeline build
(rag_engine.run_rag_pipeline) and the incremental indexer (indexer.py), so a
document chunked at upload time is split and cleaned identically to one chunked
during a from-scratch rebuild -- their vectors land in the same space.
"""

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

# Chunks shorter than this after cleaning are dropped as formatting garbage.
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
    """
    text = (text or "").replace("\x00", "").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # normalize line endings
    text = re.sub(r"[^\S\n]+", " ", text)   # collapse spaces/tabs, keep newlines
    text = re.sub(r" *\n *", "\n", text)     # trim spaces hugging newlines
    text = re.sub(r"\n{3,}", "\n\n", text)   # cap blank-line runs at one
    return text.strip()


def chunk_and_clean(documents, min_chars: int = _MIN_CHUNK_CHARS):
    """Split LangChain documents into cleaned chunks.

    Returns the list of chunk Documents with cleaned page_content, dropping any
    chunk left with fewer than ``min_chars`` characters.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )
    cleaned = []
    for split in splitter.split_documents(documents):
        text = clean_chunk_text(split.page_content)
        if len(text) > min_chars:
            split.page_content = text
            cleaned.append(split)
    return cleaned
