"""Native (cheap) text extraction per file format.

This is the first, fast tier of ingestion: pull whatever text already exists in
the file without OCR. Heavy libraries are imported lazily inside each function
so importing this module never fails just because an optional loader is absent.
"""

import os


def file_extension(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def extract_text_layer(path: str) -> tuple[str, int]:
    """Return (text, page_count) from the file's native text layer.

    - pdf  -> pypdfium2 (PDFium): reads the embedded text layer (empty for scans).
    - docx -> docx2txt.
    - txt/md -> read as UTF-8.

    page_count is 1 for non-paged formats. Raises ValueError for unsupported
    extensions.
    """
    ext = file_extension(path)

    if ext == "pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        try:
            parts = []
            for i in range(len(pdf)):
                page = pdf[i]
                textpage = page.get_textpage()
                try:
                    parts.append(textpage.get_text_range() or "")
                finally:
                    textpage.close()
                    page.close()
            return "\n".join(parts), len(pdf)
        finally:
            pdf.close()

    if ext == "docx":
        import docx2txt

        return (docx2txt.process(path) or ""), 1

    if ext in ("txt", "md"):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(), 1

    raise ValueError(f"Unsupported file type for ingestion: .{ext}")


def pdf_page_count(path: str) -> int:
    """Return the number of pages in a PDF."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()
