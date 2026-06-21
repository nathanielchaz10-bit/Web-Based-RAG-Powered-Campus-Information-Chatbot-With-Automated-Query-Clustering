"""Tiered document-ingestion pipeline.

One entry point, ``ingest_document``, that turns any supported file into clean
retrievable text plus a confidence verdict, choosing the cheapest method that
works:

    1. native text layer (instant, free)        -> digital PDFs/docx/txt; for
       docx, native Word tables are rendered as Markdown (structure preserved)
    2. OCR, applied PER PAGE                      -> recovers scanned/image-heavy
       pages even inside an otherwise-digital PDF; for docx, OCRs the pictures
       embedded in the file (text trapped in diagrams/screenshots)
    3. optional LLM cleanup of OCR output        -> de-noises tables/garble

``force_ocr`` overrides the per-page heuristic and OCRs everything with a
color/layout-aware prompt -- for docs whose meaning lives in layout + color
coding (a calendar's vector cell-shading) that the text layer simply can't carry
and the image-coverage heuristic can't see. For a docx this renders the file to
PDF first (LibreOffice) so its pages can be OCR'd like any PDF; without
LibreOffice it falls back to the text layer + embedded-image OCR.

It also reports how it got the text and whether the result is trustworthy
(``confidence`` / ``needs_review``), which is what an admin upload flow needs to
decide whether a document can go live or should be eyeballed first.
"""

from dataclasses import dataclass, asdict

from app.core.config import settings
from app.services.ingestion import extractors, ocr as ocr_mod, quality


@dataclass
class IngestionResult:
    text: str
    method: str          # "text_layer" | "ocr:<backend>" | "hybrid:<backend>"
    pages: int
    chars: int
    chars_per_page: float
    confidence: str      # "high" | "medium" | "low"
    needs_review: bool
    cleaned: bool         # whether an LLM cleanup pass ran
    ocr_used: bool        # whether OCR contributed any text (drives sidecar save)

    def summary(self) -> dict:
        """Everything except the (potentially large) text, for logging/UI."""
        d = asdict(self)
        d.pop("text", None)
        d["chars"] = self.chars
        return d


def _ingest_pdf(path, *, force_ocr, ocr_backend, text_min_cpp, cov_threshold):
    """Per-page PDF ingestion. Returns (text, method, pages, ocr_used)."""
    page_texts = extractors.extract_pdf_pages(path)
    pages = len(page_texts) or 1

    try:
        coverages = extractors.pdf_page_image_coverage(path)
    except Exception:
        coverages = []
    # Align coverage list length to the page list (defensive).
    if len(coverages) < len(page_texts):
        coverages += [0.0] * (len(page_texts) - len(coverages))

    # Which pages get OCR'd? (force, or scanned/image-heavy by the heuristic.)
    to_ocr = [
        i for i, t in enumerate(page_texts)
        if quality.page_needs_ocr(
            len(t.strip()), coverages[i],
            force=force_ocr, text_min_chars=text_min_cpp,
            coverage_threshold=cov_threshold,
        )
    ]

    ocr_map = {}
    if to_ocr:
        try:
            backend = ocr_mod.get_page_ocr_backend(ocr_backend)
            ocr_map = backend(path, pages=to_ocr, color_aware=force_ocr) or {}
        except Exception:
            ocr_map = {}  # OCR unavailable/failed -> fall back to the text layer

    # Merge per page: prefer OCR for forced pages (it carries layout/color the
    # text layer lacks); otherwise keep whichever recovered more text.
    final_pages = []
    for i, t in enumerate(page_texts):
        base = t.strip()
        otext = (ocr_map.get(i) or "").strip()
        if otext and (force_ocr or len(otext) >= len(base)):
            final_pages.append(otext)
        else:
            final_pages.append(base)
    text = "\n\n".join(p for p in final_pages if p)

    ocr_used = any((ocr_map.get(i) or "").strip() for i in to_ocr)
    if not ocr_used:
        method = "text_layer"
    elif len(to_ocr) >= pages:
        method = f"ocr:{ocr_backend}"
    else:
        method = f"hybrid:{ocr_backend}"
    return text, method, pages, ocr_used


def _ingest_docx(path, *, force_ocr, ocr_backend, text_min_cpp, cov_threshold,
                 docx_min_pixels):
    """docx ingestion. Returns (text, method, pages, ocr_used).

    Normal path: native text layer (python-docx -- native Word tables become
    Markdown) plus OCR of any images embedded in the file. Force-OCR path:
    render the docx to PDF (LibreOffice) and OCR every page with the layout/
    color-aware prompt -- the only way to carry a native table's grid or color
    coding -- then fall back to the text + embedded-image path if LibreOffice
    isn't installed."""
    if force_ocr:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="docx_ocr_") as tmp:
            pdf_path = extractors.docx_to_pdf(path, out_dir=tmp)
            if pdf_path:
                # Reuse the PDF path: force_ocr renders + OCRs every page. The
                # temp PDF is read fully before this returns, so cleanup is safe.
                return _ingest_pdf(
                    pdf_path, force_ocr=True, ocr_backend=ocr_backend,
                    text_min_cpp=text_min_cpp, cov_threshold=cov_threshold,
                )
        # LibreOffice unavailable -> fall through to text + embedded-image OCR.

    raw, _ = extractors.extract_text_layer(path)  # python-docx (tables -> MD)
    text = (raw or "").strip()

    # Force lowers the size filter so even small figures are read.
    min_px = 0 if force_ocr else docx_min_pixels
    images = extractors.extract_docx_images(path, min_pixels=min_px)

    ocr_used = False
    if images:
        try:
            backend = ocr_mod.get_image_ocr_backend(ocr_backend)
            img_texts = backend(images, color_aware=force_ocr) or []
        except Exception:
            img_texts = []
        extracted = [t.strip() for t in img_texts if t and t.strip()]
        if extracted:
            block = "\n\n".join(f"[Embedded image]\n{t}" for t in extracted)
            text = f"{text}\n\n{block}".strip() if text else block
            ocr_used = True

    method = f"hybrid:{ocr_backend}" if ocr_used else "text_layer"
    return text, method, 1, ocr_used


def ingest_document(
    path: str,
    *,
    force_ocr: bool = False,
    ocr_backend: str | None = None,
    llm_cleanup: bool | None = None,
    text_min_cpp: int | None = None,
    ocr_min_cpp: int | None = None,
    image_cov_threshold: float | None = None,
    docx_min_image_pixels: int | None = None,
) -> IngestionResult:
    """Ingest one file into text with a confidence verdict.

    Args mirror the INGEST_* settings and override them when provided (handy for
    the comparison script / tests). ``force_ocr`` makes a PDF OCR every page with
    the color/layout-aware prompt and a docx OCR all of its embedded images.
    """
    ocr_backend = ocr_backend or settings.INGEST_OCR_BACKEND
    llm_cleanup = settings.INGEST_LLM_CLEANUP if llm_cleanup is None else llm_cleanup
    text_min_cpp = text_min_cpp or settings.INGEST_TEXT_MIN_CHARS_PER_PAGE
    ocr_min_cpp = ocr_min_cpp or settings.INGEST_OCR_MIN_CHARS_PER_PAGE
    cov_threshold = (
        image_cov_threshold if image_cov_threshold is not None
        else settings.INGEST_PAGE_IMAGE_COVERAGE
    )
    docx_min_px = (
        docx_min_image_pixels if docx_min_image_pixels is not None
        else settings.INGEST_DOCX_MIN_IMAGE_PIXELS
    )

    ext = extractors.file_extension(path)
    if ext == "pdf":
        text, method, pages, ocr_used = _ingest_pdf(
            path, force_ocr=force_ocr, ocr_backend=ocr_backend,
            text_min_cpp=text_min_cpp, cov_threshold=cov_threshold,
        )
    elif ext == "docx":
        text, method, pages, ocr_used = _ingest_docx(
            path, force_ocr=force_ocr, ocr_backend=ocr_backend,
            text_min_cpp=text_min_cpp, cov_threshold=cov_threshold,
            docx_min_pixels=docx_min_px,
        )
    else:
        # txt/md straight from the text layer (raises ValueError for unknown ext).
        raw, pages = extractors.extract_text_layer(path)
        text, method, ocr_used = (raw or "").strip(), "text_layer", False

    # Optional LLM cleanup pass over OCR output (reformat tables, fix noise).
    cleaned = False
    if ocr_used and llm_cleanup:
        from app.services.ingestion.cleanup import llm_clean

        cleaned_text = (llm_clean(text) or "").strip()
        if cleaned_text:
            text, cleaned = cleaned_text, True

    final_chars = len(text.strip())
    final_cpp = final_chars / max(pages, 1)
    confidence, needs_review = quality.grade_confidence(method, final_cpp, ocr_min_cpp)

    return IngestionResult(
        text=text,
        method=method,
        pages=pages,
        chars=final_chars,
        chars_per_page=round(final_cpp, 1),
        confidence=confidence,
        needs_review=needs_review,
        cleaned=cleaned,
        ocr_used=ocr_used,
    )
