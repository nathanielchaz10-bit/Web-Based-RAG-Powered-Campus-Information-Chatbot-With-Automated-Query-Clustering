"""End-to-end tests for the admin Documents API (upload -> ingest -> index).

Exercises the real FastAPI app (startup, migrations, role seeding, auth dev
fallback), the real ingestion routing, real chunking, and the real DB writes.
Only the Gemini *network* boundary is faked -- the vision-OCR backend and the
embedding/vector-store calls -- so the whole flow runs with NO API key and NO
network. Everything around those two calls is the production code path.

Mirrors the repo's test-script style (see scripts/test_ingestion.py): run it
directly, it asserts + prints, exits 0 on success / 1 on any failure.

    python scripts/test_documents_api.py

What it covers:
  * digital docx/pdf  -> native text layer, indexed live, placed in uploads/<sub>/
  * scanned pdf       -> OCR path, indexed, OCR text saved as a sidecar .txt
  * unreadable scan   -> low confidence, held for review (not indexed)
  * approve           -> a held doc gets indexed and goes live
  * delete            -> file, DB rows, and vectors all removed
  * unsupported type  -> rejected with 400
  * indexing failure  -> held gracefully (no 500), reason surfaced to the caller
  * every chunk fails -> held, never marked active with zero chunks
"""

import os
import sys
import shutil
import tempfile

# --- App root on sys.path (scripts/ -> hccs_rag_chatbot/) ------------------
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_ROOT)
FIXTURES = os.path.join(APP_ROOT, "uploads")  # real sample docs shipped in repo

# --- Hermetic paths + no API key: set BEFORE importing app modules, because
# config reads these at import time and documents.py derives an uploads anchor
# at import time too. UPLOADS_PATH basename must be "uploads" (the app stores
# file paths relative to the uploads parent). ------------------------------
_TMP = tempfile.mkdtemp(prefix="hccs_doctest_")
UPLOADS = os.path.join(_TMP, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
os.environ["UPLOADS_PATH"] = UPLOADS
os.environ["SQLITE_DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CHROMA_DB_PATH"] = os.path.join(_TMP, "chroma")
os.environ["DEV_MODE"] = "True"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)

from PIL import Image                         # noqa: E402
from fastapi.testclient import TestClient     # noqa: E402

import app.services.rag.indexer as indexer    # noqa: E402
import app.services.ingestion.ocr as ocr_mod  # noqa: E402
from app.core.database import SessionLocal    # noqa: E402
from app.models.document import Document       # noqa: E402
from app.models.document_chunk import DocumentChunk  # noqa: E402

# ----------------------- Gemini boundary fakes -----------------------------
# A toggleable in-memory stand-in for the Chroma vector store + the OCR backend.
STATE = {"get_should_fail": False, "add_should_fail": False, "ocr_text": "word " * 300}


class _FakeCollection:
    def __init__(self):
        self.deleted = []

    def delete(self, where=None):
        self.deleted.append(where)

    def count(self):
        return 0


class _FakeVectorstore:
    def __init__(self):
        self.added = []
        self._collection = _FakeCollection()

    def add_documents(self, docs, ids=None):
        if STATE["add_should_fail"]:
            raise RuntimeError("simulated embedding failure")
        self.added.append((ids, [d.page_content for d in docs]))


FAKE = _FakeVectorstore()


def _fake_get_vectorstore():
    if STATE["get_should_fail"]:
        raise RuntimeError("API key required for Gemini (simulated)")
    return FAKE


def _fake_get_ocr_backend(name):
    return lambda path, dpi=None: STATE["ocr_text"]


# index_document_text() resolves get_vectorstore from its module globals, and
# the pipeline imports get_ocr_backend lazily from the ocr module, so patching
# the module attributes is enough.
indexer.get_vectorstore = _fake_get_vectorstore
ocr_mod.get_ocr_backend = _fake_get_ocr_backend

from main import app  # noqa: E402  (import AFTER env + patches are in place)

_RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    _RESULTS.append(ok)
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  -- {detail}" if (detail and not ok) else ""))


def db_doc(doc_id):
    """Read a document's persisted state straight from the DB."""
    db = SessionLocal()
    try:
        d = db.query(Document).get(doc_id)
        if not d:
            return None
        return {
            "is_active": d.is_active,
            "needs_review": d.needs_review,
            "method": d.extraction_method,
            "file_path": d.file_path,
            "chunks": db.query(DocumentChunk).filter_by(document_id=doc_id).count(),
        }
    finally:
        db.close()


def _upload(client, path, name, ctype, doc_type):
    with open(path, "rb") as fh:
        return client.post(
            "/documents/upload",
            files={"file": (name, fh, ctype)},
            data={"document_type": doc_type},
        )


def main():
    # raise_server_exceptions=False so an unhandled 500 is an assertable
    # response instead of crashing the run (it must NOT regress to a 500).
    with TestClient(app, raise_server_exceptions=False) as client:
        print("\n-- empty list --")
        r = client.get("/documents")
        check("GET /documents empty", r.status_code == 200 and r.json() == [], r.text)

        print("\n-- digital docx -> text_layer, indexed, uploads/docs/ --")
        r = _upload(
            client,
            os.path.join(FIXTURES, "docs", "Scholarships_Programs.docx"),
            "Scholarships_Programs.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "FINANCIAL",
        )
        j = r.json()
        check("docx upload 200", r.status_code == 200, r.text)
        check("docx method text_layer", j.get("extraction_method") == "text_layer", str(j))
        check("docx indexed", j.get("indexed") is True, str(j))
        check("docx chunk_count > 0", j.get("chunk_count", 0) > 0, str(j))
        docx_id = j.get("document_id")
        d = db_doc(docx_id)
        check("docx placed in uploads/docs/", d and d["file_path"] == "uploads/docs/Scholarships_Programs.docx", str(d))
        check("docx file on disk", os.path.exists(os.path.join(UPLOADS, "docs", "Scholarships_Programs.docx")))
        check("docx DocumentChunk rows == chunk_count", d and d["chunks"] == j["chunk_count"], str(d))
        check("docx is_active", d and d["is_active"] is True, str(d))

        print("\n-- digital pdf -> text_layer, uploads/pdf/ --")
        r = _upload(
            client,
            os.path.join(FIXTURES, "pdf", "2025-2026_School_Calendar.pdf"),
            "2025-2026_School_Calendar.pdf",
            "application/pdf",
            "CALENDAR",
        )
        j = r.json()
        check("pdf upload 200", r.status_code == 200, r.text)
        check("pdf method text_layer", j.get("extraction_method") == "text_layer", str(j))
        check("pdf placed in uploads/pdf/", os.path.exists(os.path.join(UPLOADS, "pdf", "2025-2026_School_Calendar.pdf")))

        print("\n-- scanned pdf -> OCR, indexed, sidecar .txt --")
        STATE["ocr_text"] = "word " * 400
        r = _upload(
            client,
            os.path.join(FIXTURES, "pdf", "HCCS_School_Facilities_Directory.pdf"),
            "HCCS_School_Facilities_Directory.pdf",
            "application/pdf",
            "DIRECTORY",
        )
        j = r.json()
        check("scan upload 200", r.status_code == 200, r.text)
        check("scan method ocr:gemini", j.get("extraction_method") == "ocr:gemini", str(j))
        check("scan indexed", j.get("indexed") is True, str(j))
        check("scan sidecar .txt written",
              os.path.exists(os.path.join(UPLOADS, "txt", "HCCS_School_Facilities_Directory.txt")))

        print("\n-- unreadable scan -> held for review --")
        STATE["ocr_text"] = "x"  # OCR recovers almost nothing
        blank = os.path.join(_TMP, "blank.pdf")
        Image.new("RGB", (850, 1100), "white").save(blank)  # image-only, no text layer
        r = _upload(client, blank, "blank.pdf", "application/pdf", "OTHER")
        j = r.json()
        check("blank upload 200", r.status_code == 200, r.text)
        check("blank needs_review", j.get("needs_review") is True, str(j))
        check("blank not indexed", j.get("indexed") is False, str(j))
        held_id = j.get("document_id")
        d = db_doc(held_id)
        check("blank is_active False", d and d["is_active"] is False, str(d))
        check("blank 0 chunks", d and d["chunks"] == 0, str(d))
        r = client.get("/documents")
        held = [x for x in r.json() if x["document_id"] == held_id]
        check("blank appears in list as held", len(held) == 1 and held[0]["needs_review"] is True)

        print("\n-- approve held doc -> indexed --")
        STATE["ocr_text"] = "word " * 400  # this time OCR recovers good text
        r = client.post(f"/documents/{held_id}/approve", json={})
        j = r.json()
        check("approve 200", r.status_code == 200, r.text)
        check("approve indexed", j.get("indexed") is True, str(j))
        d = db_doc(held_id)
        check("approved is_active", d and d["is_active"] is True, str(d))
        check("approved needs_review False", d and d["needs_review"] is False, str(d))
        check("approved chunks > 0", d and d["chunks"] > 0, str(d))

        print("\n-- delete -> file, rows, vectors removed --")
        before = len(FAKE._collection.deleted)
        r = client.delete(f"/documents/{docx_id}")
        check("delete 200", r.status_code == 200, r.text)
        check("delete removed file", not os.path.exists(os.path.join(UPLOADS, "docs", "Scholarships_Programs.docx")))
        check("delete removed db row", db_doc(docx_id) is None)
        check("delete called vector remove", len(FAKE._collection.deleted) == before + 1)

        print("\n-- unsupported type -> 400 --")
        r = client.post(
            "/documents/upload",
            files={"file": ("notes.csv", b"a,b,c\n1,2,3", "text/csv")},
            data={"document_type": "OTHER"},
        )
        check("csv rejected 400", r.status_code == 400, r.text)

        print("\n-- indexing failure -> graceful hold, not 500 --")
        STATE["get_should_fail"] = True  # mimic missing/invalid key or quota
        r = _upload(
            client,
            os.path.join(FIXTURES, "docs", "Enrollment_Schedule_Process.docx"),
            "Enrollment_Schedule_Process.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "ENROLLMENT",
        )
        check("index-fail not 500", r.status_code != 500, f"{r.status_code} {r.text[:200]}")
        jf = r.json() if r.status_code == 200 else {}
        check("index-fail held (needs_review)", jf.get("needs_review") is True, str(jf))
        check("index-fail not indexed", jf.get("indexed") is False, str(jf))
        check("index-fail reports index_error", bool(jf.get("index_error")), str(jf))
        fid = jf.get("document_id")
        df = db_doc(fid) if fid else None
        check("index-fail doc is_active False", df and df["is_active"] is False, str(df))
        STATE["get_should_fail"] = False

        print("\n-- every chunk fails -> held, never active-with-zero-chunks --")
        STATE["add_should_fail"] = True
        r = _upload(
            client,
            os.path.join(FIXTURES, "txt", "HCCS_School_Facilities_Directory.txt"),
            "zero.txt",
            "text/plain",
            "OTHER",
        )
        j = r.json() if r.status_code == 200 else {}
        zid = j.get("document_id")
        dz = db_doc(zid) if zid else None
        check("zero-chunk not marked active+indexed",
              not (j.get("indexed") and dz and dz["is_active"] and dz["chunks"] == 0),
              str(j) + " / " + str(dz))
        STATE["add_should_fail"] = False

    total, passed = len(_RESULTS), sum(_RESULTS)
    print(f"\n==== {passed}/{total} checks passed ====")
    shutil.rmtree(_TMP, ignore_errors=True)
    if passed != total:
        sys.exit(1)
    print("All documents API tests passed.")


if __name__ == "__main__":
    main()
