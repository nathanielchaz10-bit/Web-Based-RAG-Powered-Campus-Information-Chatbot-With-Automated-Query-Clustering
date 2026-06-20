"""OCR backends for scanned PDFs, behind one common interface.

Two engines, same signature ``ocr_pdf(path, dpi) -> str``:

  * tesseract -- local, free, offline. Solid on prose; weaker on tables/grids
    (it linearizes cells and introduces border noise).
  * gemini    -- sends each rendered page image to a Gemini vision model and
    asks it to transcribe. Much better on tables/layout and can emit markdown
    tables, at the cost of an API call per page (ingestion-time only).

Pages are rendered with PyMuPDF (no poppler/system renderer needed). All heavy
imports are lazy so this module imports cleanly without the optional deps.
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


def _render_pdf_pages(path: str, dpi: int) -> Iterator:
    """Yield each PDF page as a PIL Image, rendered at the given DPI.

    Uses pypdfium2 (PDFium): pure prebuilt wheels, no system dependency and no
    build toolchain required. PDFium's render scale is in units of 72 DPI.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                yield page.render(scale=dpi / 72).to_pil()
            finally:
                page.close()
    finally:
        pdf.close()


def tesseract_ocr(path: str, dpi: int | None = None) -> str:
    """OCR every page with local Tesseract; join with blank lines."""
    import pytesseract

    dpi = dpi or settings.INGEST_OCR_DPI
    pages = []
    for img in _render_pdf_pages(path, dpi):
        pages.append(pytesseract.image_to_string(img).strip())
    return "\n\n".join(p for p in pages if p)


def gemini_vision_ocr(path: str, dpi: int | None = None) -> str:
    """OCR every page with a Gemini vision model.

    Requires settings.GEMINI_API_KEY. Uses a lower default DPI than Tesseract
    because the vision model doesn't need as much resolution and smaller images
    keep the request light.
    """
    import base64
    import io

    import app.services._engine_bootstrap  # noqa: F401  (loads .env + bridges the API key)
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    dpi = dpi or min(settings.INGEST_OCR_DPI, 200)
    # Key comes from the environment via _engine_bootstrap, same as the RAG
    # engine -- works whether .env defines GEMINI_API_KEY or GOOGLE_API_KEY.
    llm = ChatGoogleGenerativeAI(model=settings.LLM_MODEL, temperature=0)

    pages = []
    for img in _render_pdf_pages(path, dpi):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        message = HumanMessage(
            content=[
                {"type": "text", "text": _VISION_OCR_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ]
        )
        resp = llm.invoke([message])
        pages.append((getattr(resp, "content", "") or "").strip())
    return "\n\n".join(p for p in pages if p)


_BACKENDS: dict[str, Callable[..., str]] = {
    "tesseract": tesseract_ocr,
    "gemini": gemini_vision_ocr,
}


def get_ocr_backend(name: str) -> Callable[..., str]:
    try:
        return _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"Unknown OCR backend {name!r}; choose from {sorted(_BACKENDS)}"
        )
