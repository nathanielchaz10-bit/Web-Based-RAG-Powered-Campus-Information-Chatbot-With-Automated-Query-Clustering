"""Optional LLM cleanup pass for noisy OCR output.

Tesseract output from table-heavy pages is full of broken rows, stray pipe/
underscore borders, and split words. A single low-temperature LLM call can
reflow it into clean, retrievable text. The prompt is strict about NOT adding
information -- the cleaned text becomes RAG knowledge, so fidelity beats polish.

Ingestion-time only; one call per document.
"""

from app.core.config import settings

_CLEANUP_PROMPT = (
    "The text below was extracted via OCR from a scanned school document and "
    "contains OCR noise: broken table rows, stray '|' and '_' characters, split "
    "words, and misread characters. Reformat it into clean, readable text.\n"
    "Rules:\n"
    "- Preserve ALL factual content exactly: room/area codes, names, dates, "
    "amounts, numbers.\n"
    "- Where the original was a table, render it as simple 'CODE — value' lines "
    "(one per line).\n"
    "- Fix only obvious OCR character errors; keep the wording otherwise.\n"
    "- Do NOT add, infer, summarize, or invent anything not present in the text.\n"
    "- Output only the cleaned text, nothing else."
)


def llm_clean(text: str) -> str:
    """Return an LLM-cleaned version of ``text`` (requires GEMINI_API_KEY)."""
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=0,
        google_api_key=settings.GEMINI_API_KEY or None,
    )
    resp = llm.invoke(
        [HumanMessage(content=f"{_CLEANUP_PROMPT}\n\n---\n{text}")]
    )
    return (getattr(resp, "content", "") or "").strip()
