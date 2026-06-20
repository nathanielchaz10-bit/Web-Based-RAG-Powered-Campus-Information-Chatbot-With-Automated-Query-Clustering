"""Document-ingestion quality assessment and routing decisions.

Deliberately dependency-free (stdlib only) so the routing logic that decides
"is this PDF scanned?" / "does this need human review?" can be reasoned about
and unit-tested without PyMuPDF, Tesseract, or the LLM stack installed.
"""

from dataclasses import dataclass

# Defaults; the pipeline passes the values from app settings instead.
DEFAULT_TEXT_MIN_CHARS_PER_PAGE = 100
DEFAULT_OCR_MIN_CHARS_PER_PAGE = 50


@dataclass
class ExtractionAssessment:
    chars: int
    pages: int
    chars_per_page: float
    looks_scanned: bool


def assess_extraction(
    chars: int, pages: int, min_chars_per_page: int = DEFAULT_TEXT_MIN_CHARS_PER_PAGE
) -> ExtractionAssessment:
    """Judge a native text-layer extraction.

    A PDF whose text layer yields very few characters per page is almost
    certainly scanned/image-only (our facilities directory gave ~4 chars/page
    across 17 pages) and should be routed to OCR.
    """
    pages = max(int(pages), 1)
    cpp = chars / pages
    return ExtractionAssessment(
        chars=chars,
        pages=pages,
        chars_per_page=cpp,
        looks_scanned=cpp < min_chars_per_page,
    )


def grade_confidence(
    method: str,
    chars_per_page: float,
    ocr_min_chars_per_page: int = DEFAULT_OCR_MIN_CHARS_PER_PAGE,
) -> tuple[str, bool]:
    """Return (confidence_label, needs_review) for a finished extraction.

    - Native text layer -> "high", no review (digital document read directly).
    - OCR/vision that recovered a healthy amount of text -> "medium".
    - OCR/vision that still came back nearly empty -> "low" + needs_review:
      the source is genuinely unreadable (bad scan, photo, blank), so a human
      should look before it is trusted as knowledge.
    """
    if method == "text_layer":
        return "high", False
    if chars_per_page >= ocr_min_chars_per_page:
        return "medium", False
    return "low", True
