"""Standalone tests for the ingestion routing logic.

Mirrors the repo's existing test-script style (see database/test_insert.py):
run directly, asserts + prints, exit 0 on success. Uses monkeypatched
extraction/OCR so it needs no Tesseract binary, no API key, and no real files.

    python scripts/test_ingestion.py

Covers the per-page OCR routing: a digital PDF skips OCR, a scanned PDF is
OCR'd, a PDF with only SOME scanned pages is "hybrid", Force-OCR overrides the
heuristic (and uses the color-aware prompt), and a docx OCRs its embedded
images.
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

    assert quality.grade_confidence("text_layer", 3000) == ("high", False)
    assert quality.grade_confidence("ocr:gemini", 700) == ("medium", False)
    assert quality.grade_confidence("hybrid:gemini", 700) == ("medium", False)
    assert quality.grade_confidence("ocr:gemini", 10, 50) == ("low", True)

    # Per-page OCR decision.
    assert quality.page_needs_ocr(0, 1.2, text_min_chars=100) is True       # no text -> scan
    assert quality.page_needs_ocr(3000, 0.0, text_min_chars=100) is False   # rich text page
    assert quality.page_needs_ocr(3000, 0.0, force=True) is True            # forced
    # mostly-image page with only a little text -> OCR; full-text page -> no.
    assert quality.page_needs_ocr(50, 0.8, text_min_chars=100) is True
    assert quality.page_needs_ocr(5000, 0.8, text_min_chars=100) is False
    print("test_quality: PASS")


def _patch_pdf(pages, coverage, ocr_returns):
    """pages: per-page text-layer text. coverage: per-page raster coverage.
    ocr_returns: text each OCR'd page yields. Records the color_aware flag."""
    rec = {}
    extractors.extract_pdf_pages = lambda path: pages
    extractors.pdf_page_image_coverage = lambda path: coverage

    def backend(name):
        def run(path, pages=None, color_aware=False):
            rec["color_aware"] = color_aware
            rec["ocr_pages"] = list(pages or [])
            return {i: ocr_returns for i in (pages or [])}
        return run

    ocr_mod.get_page_ocr_backend = backend
    return rec


def test_pdf_routing():
    # 1. Digital PDF (every page has text) -> text_layer, OCR never runs.
    rec = _patch_pdf(["A" * 2000, "B" * 2000], [0.0, 0.0], "SHOULD NOT BE USED")
    r = pipeline.ingest_document("doc.pdf")
    assert r.method == "text_layer" and r.confidence == "high", r.summary()
    assert r.ocr_used is False and rec.get("ocr_pages") is None, rec

    # 2. Fully scanned PDF -> OCR recovers text on every page -> ocr + medium.
    _patch_pdf(["", ""], [1.1, 1.1], "word " * 200)
    r = pipeline.ingest_document("scan.pdf")
    assert r.method == "ocr:gemini" and r.confidence == "medium", r.summary()
    assert r.needs_review is False and r.ocr_used is True

    # 3. Scanned PDF where OCR ALSO comes back near-empty -> low + review.
    _patch_pdf(["", ""], [1.1, 1.1], "x")
    r = pipeline.ingest_document("badscan.pdf")
    assert r.method == "ocr:gemini" and r.confidence == "low", r.summary()
    assert r.needs_review is True

    # 4. Mixed: page 0 digital, page 1 image-only -> hybrid (only page 1 OCR'd).
    rec = _patch_pdf(["Lots of real text " * 20, ""], [0.0, 1.2], "OCR-RECOVERED")
    r = pipeline.ingest_document("mixed.pdf")
    assert r.method == "hybrid:gemini", r.summary()
    assert rec["ocr_pages"] == [1], rec
    assert "real text" in r.text and "OCR-RECOVERED" in r.text

    # 5. Force-OCR a digital PDF -> OCR all pages with the COLOR-AWARE prompt.
    rec = _patch_pdf(["A" * 2000], [0.0], "word " * 200)
    r = pipeline.ingest_document("calendar.pdf", force_ocr=True)
    assert r.method == "ocr:gemini" and r.ocr_used is True, r.summary()
    assert rec["color_aware"] is True and rec["ocr_pages"] == [0], rec
    print("test_pdf_routing: PASS")


def test_docx():
    extractors.extract_text_layer = lambda path: ("Plain docx prose.", 1)

    # docx with an embedded image -> OCR it, append, method hybrid.
    extractors.extract_docx_images = lambda path, min_pixels=0: ["IMG"]
    rec = {}

    def img_backend(name):
        def run(images, color_aware=False):
            rec["color_aware"] = color_aware
            return ["TEXT FROM DIAGRAM"]
        return run

    ocr_mod.get_image_ocr_backend = img_backend
    r = pipeline.ingest_document("notes.docx")
    assert r.method == "hybrid:gemini" and r.ocr_used is True, r.summary()
    assert "Plain docx prose." in r.text and "TEXT FROM DIAGRAM" in r.text

    # Force lowers the image-size filter (min_pixels=0) and flags color-aware.
    captured = {}
    extractors.extract_docx_images = lambda path, min_pixels=0: captured.update(min_pixels=min_pixels) or ["IMG"]
    pipeline.ingest_document("notes.docx", force_ocr=True)
    assert captured["min_pixels"] == 0 and rec["color_aware"] is True, (captured, rec)

    # docx with no images -> plain text_layer, no OCR.
    extractors.extract_docx_images = lambda path, min_pixels=0: []
    r = pipeline.ingest_document("plain.docx")
    assert r.method == "text_layer" and r.ocr_used is False, r.summary()
    print("test_docx: PASS")


if __name__ == "__main__":
    test_quality()
    test_pdf_routing()
    test_docx()
    print("\nAll ingestion tests passed.")
