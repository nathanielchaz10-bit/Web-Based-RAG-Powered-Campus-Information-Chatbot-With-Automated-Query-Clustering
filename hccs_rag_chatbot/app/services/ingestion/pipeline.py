"""Tiered document-ingestion pipeline.

One entry point, ``ingest_document``, that turns any supported file into clean
retrievable text plus a confidence verdict, choosing the cheapest method that
works:

    1. native text layer (instant, free)        -> most digital PDFs/docx/txt
    2. OCR fallback for scanned PDFs             -> recovers image-only pages
    3. optional LLM cleanup of OCR output        -> de-noises tables/garble

It also reports how it got the text and whether the result is trustworthy
(``confidence`` / ``needs_review``), which is what an admin upload flow needs to
decide whether a document can go live or should be eyeballed first.
"""

from dataclasses import dataclass, asdict

from app.core.config import settings
from app.services.ingestion import extractors, quality


@dataclass
class IngestionResult:
    text: str
    method: str          # "text_layer" | "ocr:tesseract" | "ocr:gemini"
    pages: int
    chars: int
    chars_per_page: float
    confidence: str      # "high" | "medium" | "low"
    needs_review: bool
    cleaned: bool         # whether an LLM cleanup pass ran

    def summary(self) -> dict:
        """Everything except the (potentially large) text, for logging/UI."""
        d = asdict(self)
        d.pop("text", None)
        d["chars"] = self.chars
        return d


def ingest_document(
    path: str,
    *,
    ocr_backend: str | None = None,
    llm_cleanup: bool | None = None,
    text_min_cpp: int | None = None,
    ocr_min_cpp: int | None = None,
) -> IngestionResult:
    """Ingest one file into text with a confidence verdict.

    Args mirror the INGEST_* settings and override them when provided (handy for
    the comparison script / tests). OCR only ever applies to scanned PDFs;
    docx/txt always come straight from the text layer.
    """
    ocr_backend = ocr_backend or settings.INGEST_OCR_BACKEND
    llm_cleanup = settings.INGEST_LLM_CLEANUP if llm_cleanup is None else llm_cleanup
    text_min_cpp = text_min_cpp or settings.INGEST_TEXT_MIN_CHARS_PER_PAGE
    ocr_min_cpp = ocr_min_cpp or settings.INGEST_OCR_MIN_CHARS_PER_PAGE

    ext = extractors.file_extension(path)

    # Tier 1: native text layer.
    text, pages = extractors.extract_text_layer(path)
    text = text or ""
    assessment = quality.assess_extraction(len(text.strip()), pages, text_min_cpp)
    method = "text_layer"
    cleaned = False

    # Tier 2: OCR fallback -- only for scanned-looking PDFs.
    if ext == "pdf" and assessment.looks_scanned:
        from app.services.ingestion.ocr import get_ocr_backend

        ocr_text = (get_ocr_backend(ocr_backend)(path) or "").strip()
        # Only adopt OCR if it actually recovered more than the text layer.
        if len(ocr_text) > len(text.strip()):
            text = ocr_text
            method = f"ocr:{ocr_backend}"

            # Tier 3: optional LLM cleanup of the (noisy) OCR text.
            if llm_cleanup:
                from app.services.ingestion.cleanup import llm_clean

                cleaned_text = (llm_clean(text) or "").strip()
                if cleaned_text:
                    text = cleaned_text
                    cleaned = True

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
    )
