"""Native (cheap) text extraction per file format.

This is the first, fast tier of ingestion: pull whatever text already exists in
the file without OCR. Heavy libraries are imported lazily inside each function
so importing this module never fails just because an optional loader is absent.
"""

import os


def file_extension(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def extract_pdf_pages(path: str) -> list[str]:
    """Return the native text-layer text of each PDF page, one string per page.

    Per-page (rather than one blob) so ingestion can decide page by page whether
    a page is scanned/image-only and route just that page to OCR.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            try:
                pages.append(textpage.get_text_range() or "")
            finally:
                textpage.close()
                page.close()
        return pages
    finally:
        pdf.close()


def pdf_page_image_coverage(path: str) -> list[float]:
    """Return, per page, the fraction of the page area covered by raster images.

    Used to spot an image-heavy page (a scan/figure/screenshot) inside an
    otherwise-digital PDF. Values can exceed 1.0 when images overlap or bleed off
    the page; that's fine, we only ever compare against a threshold. Vector
    shading (e.g. a color-coded calendar grid) is NOT a raster image and so
    reads ~0 here -- which is exactly why such docs need the manual Force-OCR
    toggle, not this heuristic.
    """
    import pypdfium2 as pdfium

    def _area(obj) -> float:
        # Image objects expose get_bounds() (older get_pos() on some builds);
        # treat the 4-tuple as (x0, y0, x1, y1) regardless of corner order.
        getter = getattr(obj, "get_bounds", None) or getattr(obj, "get_pos", None)
        if not getter:
            return 0.0
        try:
            c = getter()
        except Exception:
            return 0.0
        return abs((c[2] - c[0]) * (c[3] - c[1]))

    pdf = pdfium.PdfDocument(path)
    try:
        coverages = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                w, h = page.get_size()
                page_area = (w * h) or 1.0
                image_area = sum(
                    _area(obj)
                    for obj in page.get_objects(max_depth=4)
                    if obj.type == 3  # FPDF_PAGEOBJ_IMAGE (raster)
                )
                coverages.append(image_area / page_area)
            finally:
                page.close()
        return coverages
    finally:
        pdf.close()


def extract_docx_images(path: str, *, min_pixels: int = 0) -> list:
    """Return embedded images from a .docx as PIL Images (text trapped in them is
    invisible to docx2txt).

    A .docx is a zip; its pictures live under ``word/media/``. Images whose pixel
    area is below ``min_pixels`` are skipped (logos/icons/bullets), and anything
    that isn't a decodable image is ignored.
    """
    import io
    import zipfile

    from PIL import Image

    images = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.startswith("word/media/")]
            for name in names:
                try:
                    img = Image.open(io.BytesIO(zf.read(name)))
                    img.load()
                except Exception:
                    continue  # non-image media (e.g. embedded video) or corrupt
                if (img.width * img.height) >= min_pixels:
                    images.append(img)
    except (zipfile.BadZipFile, OSError):
        return []
    return images


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
        pages = extract_pdf_pages(path)
        return "\n".join(pages), len(pages)

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
