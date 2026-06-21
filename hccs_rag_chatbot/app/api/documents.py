"""Admin document management: upload -> ingest (OCR if needed) -> index.

Endpoints (all admin-only):
  POST   /documents/upload          upload a file; it is extracted (Gemini
                                     vision OCR for scanned PDFs) and, if the
                                     extraction is confident, chunked and
                                     indexed into the RAG corpus immediately.
                                     Low-confidence extractions are saved but
                                     HELD for review (human-in-the-loop).
  GET    /documents                 list documents + their ingestion status.
  POST   /documents/{id}/approve    index a held document after admin review.
  DELETE /documents/{id}            remove a document, its chunks, and its file.

This is the backend for the "upload documents" admin feature.
"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_retrieval import DocumentRetrieval
from app.models.user_account import UserAccount
from app.services.ingestion import ingest_document
from app.services.rag import indexer, rag_service

router = APIRouter(prefix="/documents", tags=["Documents"])

# Extension -> the uploads/ subfolder it belongs in.
_SUBFOLDER = {"pdf": "pdf", "docx": "docs", "txt": "txt"}
_ALLOWED = set(_SUBFOLDER)

# Repo-relative root that file_path values are stored against (".../uploads").
_UPLOADS_PARENT = os.path.dirname(settings.UPLOADS_PATH)


def _safe_filename(name: str) -> str:
    """Keep just the basename and strip anything that isn't a tame filename
    character, so an upload can't write outside the uploads folder."""
    name = os.path.basename(name or "").strip()
    keep = [c if (c.isalnum() or c in " ._-()") else "_" for c in name]
    return "".join(keep).strip() or "upload"


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _abs_path(file_path: str) -> str:
    """Absolute path for a stored 'uploads/<sub>/<name>' file_path."""
    return os.path.join(_UPLOADS_PARENT, file_path)


# Rough chars-per-token ratio for English prose. We don't run the Gemini
# tokenizer at request time (it isn't local), and the chunker splits on
# characters, so token counts aren't stored. ~4 chars/token is the standard
# heuristic and is plenty accurate for a corpus-size headline figure.
_CHARS_PER_TOKEN = 4


def _dir_size_bytes(path: str) -> int:
    """Total on-disk size of everything under ``path`` (the Chroma store).

    Walks the directory so the figure reflects the real vector-index footprint
    (SQLite file + HNSW index segments), not an estimate. Returns 0 if the
    store hasn't been created yet.
    """
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass  # file vanished mid-walk; skip it
    return total


def _month_window(now: datetime) -> tuple[datetime, datetime]:
    """Return (this_month_start, last_month_start) as naive UTC datetimes,
    for the Document Directory's 'retrievals this month' (and trend) metric."""
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if this_start.month == 1:
        last_start = this_start.replace(year=this_start.year - 1, month=12)
    else:
        last_start = this_start.replace(month=this_start.month - 1)
    return this_start, last_start


def _index_and_record(db: Session, doc: Document, text: str) -> int:
    """Index a document's text into Chroma and persist its DocumentChunk rows.
    Returns the number of chunks indexed."""
    added = indexer.index_document_text(
        text, document_id=doc.document_id, source=doc.document_name
    )
    for vector_id, chunk_text in added:
        db.add(
            DocumentChunk(
                document_id=doc.document_id,
                chunk_text=chunk_text,
                vector_id=vector_id,
            )
        )
    return len(added)


def _store_and_extract(file: UploadFile, *, force_ocr: bool):
    """Save an uploaded file to its uploads/<sub>/ folder and extract its text.

    Shared by upload and replace. Returns (filename, subfolder, content,
    result). Raises HTTPException for a bad extension or a failed extraction
    (cleaning up the half-written file in the latter case).
    """
    filename = _safe_filename(file.filename or "")
    ext = _extension(filename)
    if ext not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(_ALLOWED)}.",
        )

    subfolder = _SUBFOLDER[ext]
    dest_dir = os.path.join(settings.UPLOADS_PATH, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)

    content = file.file.read()
    with open(dest_path, "wb") as fh:
        fh.write(content)

    # Extract text. OCR fires per page for scanned/image-heavy pages; force_ocr
    # OCRs everything with the color/layout-aware prompt (table/calendar docs).
    try:
        result = ingest_document(dest_path, force_ocr=force_ocr)
    except Exception as exc:
        # Don't leave an unusable file lying around if extraction blew up.
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise HTTPException(status_code=502, detail=f"Document extraction failed: {exc}")

    # When OCR contributed text (scanned pages, or a docx's embedded images),
    # persist the recovered text as a sidecar .txt so a future full rebuild --
    # which reads files, not the live index -- recovers it too (mirrors how the
    # seeded facilities directory is handled). When a (non-txt) file is read
    # cleanly without OCR, drop any stale sidecar from a prior OCR ingest of the
    # same name so a rebuild can't pick up outdated recovered text.
    txt_dir = os.path.join(settings.UPLOADS_PATH, "txt")
    sidecar = os.path.join(txt_dir, os.path.splitext(filename)[0] + ".txt")
    if result.ocr_used:
        os.makedirs(txt_dir, exist_ok=True)
        with open(sidecar, "w", encoding="utf-8") as fh:
            fh.write(result.text)
    elif ext != "txt" and os.path.exists(sidecar):
        try:
            os.remove(sidecar)
        except OSError:
            pass

    return filename, subfolder, content, result


def _finalize_index(db: Session, doc: Document, result) -> dict:
    """Apply an extraction result to ``doc`` and index it if confident.

    ``doc`` must already have a document_id (flushed). Copies the ingestion
    verdict onto the row, then: holds the doc for review on low confidence, and
    otherwise indexes it -- holding instead of failing if indexing produces no
    chunks. Returns {indexed, chunk_count, index_error, message}.
    """
    doc.extraction_method = result.method
    doc.extraction_confidence = result.confidence
    doc.needs_review = result.needs_review
    doc.total_token = result.chars

    indexed = False
    chunk_count = 0
    index_error = None
    message = "Saved but held for review (low extraction confidence)."

    if not result.needs_review:
        try:
            chunk_count = _index_and_record(db, doc, result.text)
        except Exception as exc:  # embedding/vector-store failure, not a DB error
            index_error = str(exc)
            chunk_count = 0

        if chunk_count > 0:
            doc.is_active = True
            doc.needs_review = False
            indexed = True
            message = "Indexed and live."
        else:
            # Extraction was fine but nothing made it into the index; hold it so
            # the doc isn't silently "active" with zero searchable chunks.
            doc.needs_review = True
            message = (
                "Saved, but indexing did not complete; held for review — "
                "fix the cause and retry with Approve."
                if index_error
                else "Saved, but no chunks could be indexed; "
                "held for review — retry with Approve."
            )

    return {
        "indexed": indexed,
        "chunk_count": chunk_count,
        "index_error": index_error,
        "message": message,
    }


def _bump_version(version: str | None) -> str:
    """Increment a 'major.minor' version string by 0.1 (1.0 -> 1.1)."""
    try:
        return f"{float(version) + 0.1:.1f}"
    except (TypeError, ValueError):
        return "1.1"


@router.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    force_ocr: bool = Form(False),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    filename, subfolder, content, result = _store_and_extract(file, force_ocr=force_ocr)

    doc = Document(
        document_name=filename,
        document_type=document_type,
        file_path=f"uploads/{subfolder}/{filename}",
        upload_size=len(content),
        uploaded_by_user_id=user.user_id,
        is_active=False,
    )
    db.add(doc)
    db.flush()  # assign document_id

    # Index the extracted text (or hold it for review). If indexing can't
    # complete -- missing/invalid API key, exhausted quota, a transient Google
    # error, or every chunk getting filtered -- the doc is HELD instead of
    # failing the upload: the file and its text are already saved, so the admin
    # can retry with "Approve" once the cause is fixed, rather than getting a
    # 500 that loses the work and explains nothing.
    outcome = _finalize_index(db, doc, result)
    db.commit()

    if outcome["indexed"]:
        rag_service.reset_chain()  # chat reloads the corpus on next query

    return {
        "document_id": doc.document_id,
        "document_name": filename,
        "document_type": document_type,
        "pages": result.pages,
        "chars": result.chars,
        "extraction_method": result.method,
        "confidence": result.confidence,
        "needs_review": doc.needs_review,
        **outcome,
    }


@router.get("")
@router.get("/")
def list_documents(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()

    # Per-document retrieval counts for this month and last month (one grouped
    # query each), used for the "N retrievals this month" activity + trend.
    this_start, last_start = _month_window(datetime.utcnow())

    def _counts(since, until=None) -> dict[int, int]:
        q = db.query(
            DocumentRetrieval.document_id, func.count().label("c")
        ).filter(DocumentRetrieval.retrieved_at >= since)
        if until is not None:
            q = q.filter(DocumentRetrieval.retrieved_at < until)
        return {row[0]: row[1] for row in q.group_by(DocumentRetrieval.document_id).all()}

    this_month = _counts(this_start)
    last_month = _counts(last_start, this_start)

    return [
        {
            "document_id": d.document_id,
            "document_name": d.document_name,
            "document_type": d.document_type,
            "is_active": d.is_active,
            "needs_review": d.needs_review,
            "extraction_method": d.extraction_method,
            "extraction_confidence": d.extraction_confidence,
            "chunk_count": len(d.chunks),
            "retrievals_this_month": this_month.get(d.document_id, 0),
            "retrievals_last_month": last_month.get(d.document_id, 0),
            "uploaded_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.get("/stats")
def corpus_stats(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Headline figures for the document-directory sidebar cards.

    - total_tokens: estimated token size of the whole indexed corpus, derived
      from the stored chunk text (sum of chunk lengths / chars-per-token).
    - vector_index_bytes: real on-disk size of the Chroma vector store.

    Both scale with how much knowledge has been ingested, so the cards now move
    as documents are added/removed instead of showing fixed placeholders.
    """
    total_chunks = db.query(func.count(DocumentChunk.chunk_id)).scalar() or 0
    total_chars = db.query(
        func.coalesce(func.sum(func.length(DocumentChunk.chunk_text)), 0)
    ).scalar() or 0

    return {
        "total_chunks": int(total_chunks),
        "total_tokens": int(total_chars) // _CHARS_PER_TOKEN,
        "vector_index_bytes": _dir_size_bytes(settings.CHROMA_DB_PATH),
    }


@router.post("/{document_id}/approve")
def approve_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Index a held (needs-review) document after an admin has eyeballed it.

    Re-extracts from the saved file (rare, deliberate action) and indexes it.
    """
    doc = db.query(Document).get(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.is_active:
        return {"document_id": document_id, "indexed": True, "message": "Already active."}

    path = _abs_path(doc.file_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Source file is no longer available.")

    # If the original ingestion used OCR (method "ocr:*" / "hybrid:*"), re-OCR on
    # approval too, so re-extraction doesn't silently fall back to a worse text
    # layer than what was first held.
    prior_ocr = (doc.extraction_method or "").split(":")[0] in ("ocr", "hybrid")
    try:
        result = ingest_document(path, force_ocr=prior_ocr)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Re-extraction failed: {exc}")

    # Index it. If indexing can't complete (API key/quota/transient error) or
    # produces no chunks, leave the document held -- never flip it to active
    # without searchable chunks -- and tell the admin why so they can retry.
    try:
        chunk_count = _index_and_record(db, doc, result.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Indexing failed: {exc}")
    if chunk_count == 0:
        raise HTTPException(
            status_code=502,
            detail="Indexing produced no chunks; document left held for review.",
        )

    doc.needs_review = False
    doc.is_active = True
    db.commit()
    rag_service.reset_chain()

    return {
        "document_id": document_id,
        "indexed": True,
        "chunk_count": chunk_count,
        "message": "Approved and indexed.",
    }


@router.post("/{document_id}/replace")
def replace_document(
    document_id: int,
    file: UploadFile = File(...),
    document_type: str = Form(None),
    force_ocr: bool = Form(False),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Replace a document's contents with a newer version of the same file.

    Keeps the SAME document_id (and therefore its retrieval history and
    analytics) while swapping in a freshly uploaded file: old vectors, chunks,
    and the prior file are removed, the new file is ingested and re-indexed, and
    the row is updated in place with its version bumped (1.0 -> 1.1). Re-uses the
    upload pipeline, so the same OCR/confidence/hold-for-review rules apply.

    ``document_type`` is optional -- omit it to keep the existing category.
    """
    doc = db.query(Document).get(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    old_path = _abs_path(doc.file_path)

    # Ingest the new file first so that, if extraction fails, the existing
    # document is left untouched (the helper deletes its own half-written file).
    filename, subfolder, content, result = _store_and_extract(file, force_ocr=force_ocr)
    new_rel = f"uploads/{subfolder}/{filename}"

    # Drop the old version's vectors and chunk rows, then its file if the new
    # upload didn't already overwrite it (different name/extension).
    indexer.remove_document(document_id)
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id
    ).delete(synchronize_session=False)
    if doc.file_path != new_rel and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    doc.document_name = filename
    if document_type:
        doc.document_type = document_type
    doc.file_path = new_rel
    doc.upload_size = len(content)
    doc.version = _bump_version(doc.version)
    doc.is_active = False
    db.flush()

    outcome = _finalize_index(db, doc, result)
    db.commit()

    # The corpus changed either way (old vectors gone, new ones maybe added), so
    # always rebuild the chat chain.
    rag_service.reset_chain()

    return {
        "document_id": doc.document_id,
        "document_name": filename,
        "document_type": doc.document_type,
        "version": doc.version,
        "pages": result.pages,
        "chars": result.chars,
        "extraction_method": result.method,
        "confidence": result.confidence,
        "needs_review": doc.needs_review,
        **outcome,
    }


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    doc = db.query(Document).get(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove its vectors, then its file, then the relational rows (chunks cascade).
    indexer.remove_document(document_id)

    path = _abs_path(doc.file_path)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    db.delete(doc)
    db.commit()
    rag_service.reset_chain()

    return {"document_id": document_id, "status": "deleted"}
