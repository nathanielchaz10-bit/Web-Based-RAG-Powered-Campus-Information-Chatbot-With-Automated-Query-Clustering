"""Compare OCR engines on a PDF: native text layer vs Tesseract vs Gemini vision.

Run this on a scanned/table-heavy PDF to decide which OCR backend to use for
ingestion. It prints character/coverage stats for each method and writes the
full output of each to a file so you can eyeball quality (especially how each
handles tables).

Usage (from hccs_rag_chatbot/):
    python scripts/compare_ocr.py "uploads/pdf/HCCS_School_Facilities_Directory.pdf"
    python scripts/compare_ocr.py <file.pdf> --engines text,tesseract,gemini --outdir /tmp/ocr

Notes:
  * Tesseract needs the system binary (apt-get install tesseract-ocr) + pytesseract.
  * Gemini needs GEMINI_API_KEY in your environment / .env.
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stats(label: str, text: str, pages: int, elapsed: float) -> None:
    text = text or ""
    cpp = len(text.strip()) / max(pages, 1)
    print(
        f"  {label:<18} chars={len(text.strip()):>7}  "
        f"~{cpp:>6.0f}/page  time={elapsed:>5.1f}s"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", help="Path to the PDF to test.")
    ap.add_argument(
        "--engines",
        default="text,tesseract,gemini",
        help="Comma list of: text, tesseract, gemini.",
    )
    ap.add_argument("--outdir", default="/tmp/ocr_compare", help="Where to write outputs.")
    ap.add_argument("--preview", type=int, default=600, help="Chars to preview per engine.")
    args = ap.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    os.makedirs(args.outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.pdf))[0]

    from app.services.ingestion import extractors

    _, pages = extractors.extract_text_layer(args.pdf)
    img_pages, total = extractors.count_pdf_image_pages(args.pdf)
    print(f"\nFile: {args.pdf}")
    print(f"Pages: {total}  |  pages-with-images: {img_pages}/{total}\n")
    print("Results:")

    outputs: dict[str, str] = {}

    if "text" in engines:
        t0 = time.perf_counter()
        text, _ = extractors.extract_text_layer(args.pdf)
        _stats("native text", text, pages, time.perf_counter() - t0)
        outputs["text"] = text

    if "tesseract" in engines:
        try:
            from app.services.ingestion.ocr import tesseract_ocr

            t0 = time.perf_counter()
            txt = tesseract_ocr(args.pdf)
            _stats("tesseract", txt, pages, time.perf_counter() - t0)
            outputs["tesseract"] = txt
        except Exception as exc:  # pragma: no cover
            print(f"  tesseract          FAILED: {exc!r}")

    if "gemini" in engines:
        try:
            from app.services.ingestion.ocr import gemini_vision_ocr

            t0 = time.perf_counter()
            txt = gemini_vision_ocr(args.pdf)
            _stats("gemini vision", txt, pages, time.perf_counter() - t0)
            outputs["gemini"] = txt
        except Exception as exc:  # pragma: no cover
            print(f"  gemini vision      FAILED: {exc!r}")

    print("\nFull outputs written to:")
    for name, txt in outputs.items():
        path = os.path.join(args.outdir, f"{base}.{name}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(txt or "")
        print(f"  {name:<12} -> {path}")

    for name, txt in outputs.items():
        print(f"\n----- {name} (first {args.preview} chars) -----")
        print((txt or "").strip()[: args.preview])


if __name__ == "__main__":
    main()
