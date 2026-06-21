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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
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


@router.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
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

    # Extract text (Gemini vision OCR for scanned PDFs, per INGEST_OCR_BACKEND).
    try:
        result = ingest_document(dest_path)
    except Exception as exc:
        # Don't leave an unusable file lying around if extraction blew up.
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise HTTPException(status_code=502, detail=f"Document extraction failed: {exc}")

    # For OCR'd (scanned) docs, persist the recovered text as a sidecar .txt so a
    # future full rebuild -- which reads files, not the live index -- recovers it
    # too (mirrors how the seeded facilities directory is handled).
    if result.method.startswith("ocr"):
        txt_dir = os.path.join(settings.UPLOADS_PATH, "txt")
        os.makedirs(txt_dir, exist_ok=True)
        sidecar = os.path.join(txt_dir, os.path.splitext(filename)[0] + ".txt")
        with open(sidecar, "w", encoding="utf-8") as fh:
            fh.write(result.text)

    doc = Document(
        document_name=filename,
        document_type=document_type,
        file_path=f"uploads/{subfolder}/{filename}",
        upload_size=len(content),
        uploaded_by_user_id=user.user_id,
        extraction_method=result.method,
        extraction_confidence=result.confidence,
        needs_review=result.needs_review,
        total_token=result.chars,
        is_active=False,
    )
    db.add(doc)
    db.flush()  # assign document_id

    # Decide what to do with the extracted text:
    #   - low extraction confidence -> hold for human review (don't index).
    #   - confident extraction -> index now; but if indexing can't complete
    #     (missing/invalid API key, exhausted quota, a transient Google error,
    #     or every chunk getting filtered) HOLD the document instead of failing
    #     the whole upload. The file and its extracted text are already saved, so
    #     holding lets the admin retry with "Approve" once the cause is fixed --
    #     far better than a 500 that loses the work and explains nothing.
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
            # the upload isn't silently "active" with zero searchable chunks. The
            # concise reason goes in `message`; the raw cause stays in
            # `index_error` for the admin/logs.
            doc.needs_review = True
            message = (
                "Saved, but indexing did not complete; held for review — "
                "fix the cause and retry with Approve."
                if index_error
                else "Saved, but no chunks could be indexed; "
                "held for review — retry with Approve."
            )

    db.commit()

    if indexed:
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
        "indexed": indexed,
        "chunk_count": chunk_count,
        "index_error": index_error,
        "message": message,
    }


@router.get("")
@router.get("/")
def list_documents(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
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
            "uploaded_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


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

    try:
        result = ingest_document(path)
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
