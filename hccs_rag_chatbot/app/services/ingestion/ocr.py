"""OCR backends for scanned PDFs and embedded images, behind one interface.

Two engines:

  * tesseract -- local, free, offline. Solid on prose; weaker on tables/grids
    (it linearizes cells and introduces border noise).
  * gemini    -- sends a rendered image to a Gemini vision model and asks it to
    transcribe. Much better on tables/layout, can emit markdown tables, and --
    with the color-aware prompt -- can read color-coded legends. Costs one API
    call per image (ingestion-time only).

Each engine is exposed three ways so ingestion can use the right granularity:

  * ``*_ocr_pages(path, pages=...)``  -> {page_index: text}  (OCR specific PDF
    pages -- lets OCR fire per page inside an otherwise-digital PDF)
  * ``*_ocr_images(images)``          -> [text, ...]         (OCR loose images,
    e.g. the pictures embedded in a .docx)
  * ``gemini_vision_ocr(path)`` / ``tesseract_ocr(path)`` -> str (whole document,
    kept for scripts/compare_ocr.py)

PDF pages are rendered with pypdfium2 (PDFium) -- no poppler/system renderer
needed. All heavy imports are lazy so this module imports cleanly without the
optional deps.
"""

from typing import Callable, Iterator

from app.core.config import settings

# --- Vision-OCR prompt: transcription, NOT interpretation. The "do not invent"
# guardrails matter -- this text becomes ground-truth knowledge for the RAG, so
# a hallucinated fee or date would be worse than a missing one.
_VISION_OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text from this document page exactly "
    "as it appears, top to bottom, left to right. Preserve tables using GitHub "
    "Markdown table syntax, keeping rows and columns aligned with the original. "
    "Do not summarize, translate, explain, or add any commentary. Do NOT invent "
    "or infer text that is not clearly present; if something is unreadable, omit "
    "it. Output only the transcribed page content."
)

# --- Color/layout-aware variant, used for the Force-OCR path (table/calendar
# docs whose meaning lives in layout + color coding the text layer can't carry).
# It still transcribes faithfully, but is allowed to read a color legend and note
# each colored cell's meaning -- the one case where naming a visual attribute is
# transcription, not invention.
_VISION_OCR_PROMPT_COLOR = (
    "You are an OCR engine for a document whose meaning depends on LAYOUT and "
    "COLOR (e.g. a calendar or a color-coded table). Transcribe ALL text exactly "
    "as it appears, top to bottom, left to right, and preserve every table using "
    "GitHub Markdown table syntax with rows and columns aligned to the original.\n"
    "If the page uses color coding with a legend that maps colors to meanings: "
    "transcribe the legend, and for each clearly color-coded entry append its "
    "meaning in brackets, e.g. `16 - Opening of Classes [green: School Day]`. "
    "Only do this where the color is unambiguous.\n"
    "Do not summarize, translate, or add commentary. Do NOT invent text or "
    "guess a color you cannot clearly see. Output only the transcribed content."
)


def _render_pdf_pages(path: str, dpi: int, pages=None) -> Iterator:
    """Yield ``(page_index, PIL Image)`` for the requested pages (all if None).

    Uses pypdfium2 (PDFium): pure prebuilt wheels, no system dependency. PDFium's
    render scale is in units of 72 DPI.
    """
    import pypdfium2 as pdfium

    want = set(pages) if pages is not None else None
    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(len(pdf)):
            if want is not None and i not in want:
                continue
            page = pdf[i]
            try:
                yield i, page.render(scale=dpi / 72).to_pil()
            finally:
                page.close()
    finally:
        pdf.close()


# ----------------------------- Gemini vision -------------------------------

def _gemini_llm():
    """Build the Gemini vision client (key bridged via _engine_bootstrap)."""
    import app.services._engine_bootstrap  # noqa: F401  (loads .env + bridges key)
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)


def _gemini_ocr_image(llm, image, prompt: str) -> str:
    """Transcribe one PIL image with the given prompt."""
    import base64
    import io

    from langchain_core.messages import HumanMessage

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
    )
    resp = llm.invoke([message])
    return (getattr(resp, "content", "") or "").strip()


def gemini_ocr_pages(path: str, pages=None, dpi: int | None = None,
                     color_aware: bool = False) -> dict:
    """OCR the given PDF pages with Gemini vision -> {page_index: text}.

    Uses a lower default DPI than Tesseract (the vision model doesn't need as
    much resolution, and smaller images keep each request light).
    """
    dpi = dpi or min(settings.INGEST_OCR_DPI, 200)
    prompt = _VISION_OCR_PROMPT_COLOR if color_aware else _VISION_OCR_PROMPT
    llm = _gemini_llm()
    return {idx: _gemini_ocr_image(llm, img, prompt)
            for idx, img in _render_pdf_pages(path, dpi, pages)}


def gemini_ocr_images(images, color_aware: bool = False) -> list:
    """OCR a list of PIL images with Gemini vision -> [text, ...]."""
    if not images:
        return []
    prompt = _VISION_OCR_PROMPT_COLOR if color_aware else _VISION_OCR_PROMPT
    llm = _gemini_llm()
    return [_gemini_ocr_image(llm, img, prompt) for img in images]


def gemini_vision_ocr(path: str, dpi: int | None = None) -> str:
    """Whole-document Gemini OCR, pages joined with blank lines (compare_ocr.py)."""
    pagemap = gemini_ocr_pages(path, pages=None, dpi=dpi)
    return "\n\n".join(pagemap[i] for i in sorted(pagemap) if pagemap[i])


# ------------------------------- Tesseract ---------------------------------

def tesseract_ocr_pages(path: str, pages=None, dpi: int | None = None,
                        color_aware: bool = False) -> dict:
    """OCR the given PDF pages with local Tesseract -> {page_index: text}.

    ``color_aware`` is accepted for a uniform interface but ignored (Tesseract
    can't read color semantics)."""
    import pytesseract

    dpi = dpi or settings.INGEST_OCR_DPI
    return {idx: pytesseract.image_to_string(img).strip()
            for idx, img in _render_pdf_pages(path, dpi, pages)}


def tesseract_ocr_images(images, color_aware: bool = False) -> list:
    """OCR a list of PIL images with local Tesseract -> [text, ...]."""
    import pytesseract

    return [pytesseract.image_to_string(img).strip() for img in (images or [])]


def tesseract_ocr(path: str, dpi: int | None = None) -> str:
    """Whole-document Tesseract OCR, pages joined with blank lines."""
    pagemap = tesseract_ocr_pages(path, pages=None, dpi=dpi)
    return "\n\n".join(pagemap[i] for i in sorted(pagemap) if pagemap[i])


# ------------------------------- Registry ----------------------------------

_PAGE_BACKENDS: dict[str, Callable[..., dict]] = {
    "tesseract": tesseract_ocr_pages,
    "gemini": gemini_ocr_pages,
}
_IMAGE_BACKENDS: dict[str, Callable[..., list]] = {
    "tesseract": tesseract_ocr_images,
    "gemini": gemini_ocr_images,
}
_WHOLE_BACKENDS: dict[str, Callable[..., str]] = {
    "tesseract": tesseract_ocr,
    "gemini": gemini_vision_ocr,
}


def _lookup(registry: dict, name: str) -> Callable:
    try:
        return registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown OCR backend {name!r}; choose from {sorted(registry)}"
        )


def get_page_ocr_backend(name: str) -> Callable[..., dict]:
    """Per-page PDF OCR backend: ``fn(path, pages=, color_aware=) -> {idx: text}``."""
    return _lookup(_PAGE_BACKENDS, name)


def get_image_ocr_backend(name: str) -> Callable[..., list]:
    """Loose-image OCR backend: ``fn(images, color_aware=) -> [text, ...]``."""
    return _lookup(_IMAGE_BACKENDS, name)


def get_ocr_backend(name: str) -> Callable[..., str]:
    """Whole-document OCR backend: ``fn(path) -> str`` (kept for compare_ocr.py)."""
    return _lookup(_WHOLE_BACKENDS, name)
