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
    collapse all runs of whitespace to single spaces."""
    text = (text or "").replace("\x00", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


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
