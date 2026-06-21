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


def _md_escape_cell(text: str) -> str:
    """Make cell text safe for a one-line GitHub Markdown table cell.

    A Markdown cell can't span lines and uses ``|`` as the column separator, so
    collapse internal whitespace/newlines to single spaces and escape any pipes.
    """
    return " ".join((text or "").split()).replace("|", "\\|")


def _table_to_markdown(table) -> str:
    """Render a python-docx ``Table`` as a GitHub Markdown table.

    Duck-typed: ``table`` only needs ``.rows`` -> objects with ``.cells`` ->
    objects with ``.text`` (so the formatting is unit-testable without
    python-docx). The first row becomes the header. Rows are padded to the widest
    row's column count; merged cells repeat their text across the spanned columns,
    which keeps columns aligned. Returns "" for an empty table.
    """
    grid = [[_md_escape_cell(c.text) for c in row.cells] for row in table.rows]
    ncols = max((len(r) for r in grid), default=0)
    if ncols == 0:
        return ""
    grid = [r + [""] * (ncols - len(r)) for r in grid]
    header, *body = grid
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def extract_docx_text(path: str) -> str:
    """Return a .docx's text with native Word tables rendered as Markdown.

    Walks the document body in order with python-docx so paragraphs and tables
    stay interleaved, turning each ``<w:tbl>`` into a GitHub Markdown table. This
    preserves the row/column structure that the old docx2txt path flattened into
    orderless cell text (a fee table's value lost its column). Falls back to
    docx2txt if python-docx is missing or the file can't be parsed that way --
    text is still preserved even when structure isn't.
    """
    try:
        import docx
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(path)
        blocks: list[str] = []
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                line = Paragraph(child, document).text.strip()
                if line:
                    blocks.append(line)
            elif isinstance(child, CT_Tbl):
                md = _table_to_markdown(Table(child, document))
                if md:
                    blocks.append(md)
        return "\n\n".join(blocks)
    except Exception:
        import docx2txt

        return docx2txt.process(path) or ""


def docx_to_pdf(path: str, out_dir: str | None = None) -> str | None:
    """Convert a .docx to PDF via headless LibreOffice; return the PDF path, or
    None if LibreOffice isn't installed or the conversion fails.

    This is what lets Force-OCR treat a docx like a PDF -- render its pages to
    images and vision-OCR them -- so a native Word table's grid or a color-coded
    layout (which neither python-docx text nor embedded-image OCR can carry) is
    captured. LibreOffice is a system dependency that pip can't provide
    (apt-get install libreoffice / brew install --cask libreoffice). A private,
    per-call user profile keeps concurrent uploads from clashing on the soffice
    lock.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    out_dir = out_dir or tempfile.mkdtemp(prefix="docx2pdf_")
    profile = os.path.join(out_dir, "lo_profile")
    try:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{profile}",
                "--headless", "--convert-to", "pdf", "--outdir", out_dir, path,
            ],
            check=True, capture_output=True, timeout=180,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    pdf = os.path.join(
        out_dir, os.path.splitext(os.path.basename(path))[0] + ".pdf"
    )
    return pdf if os.path.exists(pdf) else None


def extract_text_layer(path: str) -> tuple[str, int]:
    """Return (text, page_count) from the file's native text layer.

    - pdf  -> pypdfium2 (PDFium): reads the embedded text layer (empty for scans).
    - docx -> python-docx (native Word tables become Markdown; docx2txt fallback).
    - txt/md -> read as UTF-8.

    page_count is 1 for non-paged formats. Raises ValueError for unsupported
    extensions.
    """
    ext = file_extension(path)

    if ext == "pdf":
        pages = extract_pdf_pages(path)
        return "\n".join(pages), len(pages)

    if ext == "docx":
        return extract_docx_text(path), 1

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
