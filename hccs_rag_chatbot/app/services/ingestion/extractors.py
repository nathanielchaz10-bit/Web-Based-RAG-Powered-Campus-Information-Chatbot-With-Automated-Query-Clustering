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

    - pdf  -> PyMuPDF (fitz): reads the embedded text layer (empty for scans).
    - docx -> docx2txt.
    - txt/md -> read as UTF-8.

    page_count is 1 for non-paged formats. Raises ValueError for unsupported
    extensions.
    """
    ext = file_extension(path)

    if ext == "pdf":
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        try:
            parts = [doc[i].get_text("text") for i in range(doc.page_count)]
            return "\n".join(parts), doc.page_count
        finally:
            doc.close()

    if ext == "docx":
        import docx2txt

        return (docx2txt.process(path) or ""), 1

    if ext in ("txt", "md"):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(), 1

    raise ValueError(f"Unsupported file type for ingestion: .{ext}")


def count_pdf_image_pages(path: str) -> tuple[int, int]:
    """Return (pages_with_images, total_pages) for a PDF.

    A high ratio of image-bearing pages alongside little text is a strong
    scanned-document signal (used for diagnostics / the comparison script).
    """
    import fitz

    doc = fitz.open(path)
    try:
        img_pages = sum(1 for i in range(doc.page_count) if doc[i].get_images())
        return img_pages, doc.page_count
    finally:
        doc.close()
