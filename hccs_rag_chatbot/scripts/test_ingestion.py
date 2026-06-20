"""Standalone tests for the ingestion routing logic.

Mirrors the repo's existing test-script style (see database/test_insert.py):
run directly, asserts + prints, exit 0 on success. Uses monkeypatched
extraction/OCR so it needs no Tesseract binary, no API key, and no real files.

    python scripts/test_ingestion.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ingestion import quality
from app.services.ingestion import extractors
from app.services.ingestion import ocr as ocr_mod
from app.services.ingestion import pipeline


def test_quality():
    # Facilities-style scan: 68 chars over 17 pages -> scanned.
    a = quality.assess_extraction(68, 17, min_chars_per_page=100)
    assert a.looks_scanned is True and round(a.chars_per_page, 1) == 4.0, a
    # Calendar-style: healthy text layer -> not scanned.
    assert quality.assess_extraction(3165, 1, 100).looks_scanned is False
    # Empty/zero pages guarded.
    assert quality.assess_extraction(0, 0, 100).looks_scanned is True

    assert quality.grade_confidence("text_layer", 3000) == ("high", False)
    assert quality.grade_confidence("ocr:tesseract", 700) == ("medium", False)
    assert quality.grade_confidence("ocr:gemini", 10, 50) == ("low", True)
    print("test_quality: PASS")


def _patch(extract_return, ocr_return):
    extractors.extract_text_layer = lambda path: extract_return
    ocr_mod.get_ocr_backend = lambda name: (lambda path: ocr_return)


def test_routing():
    # 1. Digital PDF (good text layer) -> text_layer, OCR never runs.
    _patch(("A" * 2000, 1), ocr_return="SHOULD NOT BE USED")
    r = pipeline.ingest_document("doc.pdf", ocr_backend="tesseract")
    assert r.method == "text_layer" and r.confidence == "high", r.summary()

    # 2. Scanned PDF -> OCR recovers lots of text -> ocr + medium.
    _patch(("  ", 17), ocr_return="word " * 3000)
    r = pipeline.ingest_document("scan.pdf", ocr_backend="tesseract")
    assert r.method == "ocr:tesseract" and r.confidence == "medium", r.summary()
    assert r.needs_review is False

    # 3. Scanned PDF where OCR ALSO comes back near-empty -> low + review flag.
    _patch(("", 20), ocr_return="x")
    r = pipeline.ingest_document("badscan.pdf", ocr_backend="tesseract")
    assert r.method == "ocr:tesseract" and r.confidence == "low", r.summary()
    assert r.needs_review is True

    # 4. docx is never OCR'd even if short.
    _patch(("short text", 1), ocr_return="SHOULD NOT BE USED")
    r = pipeline.ingest_document("notes.docx")
    assert r.method == "text_layer", r.summary()
    print("test_routing: PASS")


if __name__ == "__main__":
    test_quality()
    test_routing()
    print("\nAll ingestion tests passed.")
