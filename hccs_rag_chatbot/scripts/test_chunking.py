"""Standalone tests for RAG chunk cleaning (app/services/rag/chunking.py).

Same style as scripts/test_ingestion.py: run directly, asserts + prints, exit 0
on success.

    python scripts/test_chunking.py

Focuses on clean_chunk_text preserving line structure (Markdown tables, the OCR
cleanup's "CODE — value" lines) while still collapsing horizontal-whitespace
noise -- so the chunks embedded into Chroma keep their tabular meaning instead
of being mashed onto a single line. chunk_and_clean is shared by BOTH the
from-scratch build (rag_engine) and incremental uploads (indexer), so this
behavior applies to every ingested document.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.documents import Document

from app.services.rag.chunking import chunk_and_clean, clean_chunk_text


def test_clean_chunk_text():
    # Markdown table: newlines kept, columns intact (the whole point).
    table = "| Fee | Amount |\n| --- | --- |\n| Tuition | $500 |"
    assert clean_chunk_text(table) == table, repr(clean_chunk_text(table))

    # Horizontal whitespace (spaces + tabs) collapses to single spaces.
    assert clean_chunk_text("foo   bar\t\tbaz") == "foo bar baz"

    # Newlines survive; spaces hugging them are trimmed.
    assert clean_chunk_text("a  \n  b") == "a\nb"

    # Runs of blank lines cap at one.
    assert clean_chunk_text("a\n\n\n\nb") == "a\n\nb"

    # CRLF / lone CR normalized to LF.
    assert clean_chunk_text("a\r\nb\rc") == "a\nb\nc"

    # Hidden Word/OCR artifacts stripped; outer whitespace trimmed.
    assert clean_chunk_text("\x00 hello\xa0world  \n") == "hello world"
    print("test_clean_chunk_text: PASS")


def test_chunk_and_clean_keeps_tables():
    md = (
        "Tuition and Fees\n\n"
        "| Fee | Amount | Due |\n"
        "| --- | --- | --- |\n"
        "| Tuition | $500 | Aug 1 |\n"
        "| Lab | $75 | Sep 1 |"
    )
    chunks = chunk_and_clean([Document(page_content=md, metadata={"source": "x"})])
    joined = "\n".join(c.page_content for c in chunks)
    # The Markdown structure survives chunking (header + separator + rows).
    assert "| Fee | Amount | Due |" in joined, joined
    assert "| --- | --- | --- |" in joined, joined
    assert "| Tuition | $500 | Aug 1 |" in joined, joined
    # Source metadata is carried onto the chunks.
    assert all(c.metadata.get("source") == "x" for c in chunks), [c.metadata for c in chunks]
    print("test_chunk_and_clean_keeps_tables: PASS")


def test_chunk_and_clean_drops_tiny():
    # A doc shorter than the min-chars threshold yields no chunks.
    assert chunk_and_clean([Document(page_content="hi", metadata={})]) == []
    print("test_chunk_and_clean_drops_tiny: PASS")


if __name__ == "__main__":
    test_clean_chunk_text()
    test_chunk_and_clean_keeps_tables()
    test_chunk_and_clean_drops_tiny()
    print("\nAll chunking tests passed.")
