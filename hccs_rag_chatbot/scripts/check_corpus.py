"""Corpus health check: documents table <-> document_chunks <-> Chroma vectors.

Prints, in one shot, what the RAG corpus actually contains and whether the three
stores agree:

  * the ``documents`` rows (name, type, how text was extracted, status)
  * how many ``document_chunks`` each has in SQLite
  * how many vectors each has in the Chroma index
  * untagged vectors from a full-corpus build (the seeded docs/, indexed without
    a document_id) so the totals make sense
  * a per-document consistency check (DB chunks vs Chroma vectors)

Read-only and needs NO API key: it only counts/reads metadata, never embeds.

    cd hccs_rag_chatbot        # run from where you launch uvicorn, so relative
    python scripts/check_corpus.py   # .env paths (e.g. CHROMA_DB_PATH) resolve the same

Point it elsewhere with --db / --chroma if your paths differ.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402  (only for default paths)

_NAME_W = 36


def _truncate(s, width):
    s = str(s if s is not None else "")
    return s if len(s) <= width else s[: width - 1] + "…"


def _fmt_int(meta_value):
    """Chroma may return numeric metadata as int or float; normalise to int."""
    try:
        return int(meta_value)
    except (TypeError, ValueError):
        return None


def read_documents(db_path):
    """Return (rows, error). rows: list of dicts from the documents table."""
    if not os.path.exists(db_path):
        return [], f"database file not found: {db_path}"
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        try:
            cur = con.execute(
                """
                SELECT d.document_id, d.document_name, d.document_type,
                       d.extraction_method, d.extraction_confidence,
                       d.is_active, d.needs_review,
                       (SELECT COUNT(*) FROM document_chunks c
                         WHERE c.document_id = d.document_id) AS db_chunks
                  FROM documents d
                 ORDER BY d.document_id
                """
            )
        except sqlite3.OperationalError as exc:
            # tables not created yet (app never ran against this DB)
            return [], f"no documents table yet ({exc})"
        return [dict(r) for r in cur.fetchall()], None
    finally:
        con.close()


def read_chroma(chroma_path):
    """Return (per_doc, untagged_sources, total, error).

    per_doc: {document_id -> vector_count} for upload-indexed (tagged) vectors.
    untagged_sources: {source -> count} for full-build vectors with no document_id.
    """
    if not os.path.isdir(chroma_path):
        # Don't instantiate a client against a missing dir (it would create one).
        return {}, {}, 0, "no Chroma store yet (folder does not exist)"
    try:
        import chromadb

        client = chromadb.PersistentClient(path=chroma_path)
        collections = client.list_collections()
    except Exception as exc:  # pragma: no cover - defensive
        return {}, {}, 0, f"could not open Chroma store: {exc!r}"

    per_doc, untagged = {}, {}
    total = 0
    for c in collections:
        name = getattr(c, "name", c)
        try:
            col = client.get_collection(name)
            total += col.count()
            data = col.get(include=["metadatas"])
        except Exception as exc:  # pragma: no cover - defensive
            return per_doc, untagged, total, f"could not read collection {name!r}: {exc!r}"
        for meta in data.get("metadatas") or []:
            meta = meta or {}
            doc_id = _fmt_int(meta.get("document_id"))
            if doc_id is not None:
                per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
            else:
                src = meta.get("source") or "(unknown source)"
                untagged[src] = untagged.get(src, 0) + 1
    return per_doc, untagged, total, None


def _status(row):
    if row["needs_review"]:
        return "held(review)"
    if row["is_active"]:
        return "active"
    return "inactive"


def main():
    parser = argparse.ArgumentParser(description="RAG corpus health check.")
    parser.add_argument("--db", default=settings.SQLITE_DB_PATH, help="SQLite DB path")
    parser.add_argument("--chroma", default=settings.CHROMA_DB_PATH, help="Chroma dir")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    chroma_path = os.path.abspath(args.chroma)

    print("=== HCCS RAG corpus check ===")
    print(f"SQLite : {db_path}  [{'ok' if os.path.exists(db_path) else 'MISSING'}]")
    print(f"Chroma : {chroma_path}  [{'ok' if os.path.isdir(chroma_path) else 'MISSING'}]")
    print()

    docs, db_err = read_documents(db_path)
    per_doc, untagged, total_vec, chroma_err = read_chroma(chroma_path)

    # --- Documents table ---------------------------------------------------
    if db_err:
        print(f"Documents: {db_err}")
    elif not docs:
        print("Documents: none uploaded yet.")
    else:
        print(f"Documents ({len(docs)})")
        print(f"  {'ID':>3}  {'NAME':<{_NAME_W}}  {'TYPE':<10}  {'METHOD':<12}  "
              f"{'CONF':<6}  {'STATUS':<12}  {'DB':>4}  {'VEC':>4}")
        for r in docs:
            vec = per_doc.get(r["document_id"], 0)
            print(f"  {r['document_id']:>3}  {_truncate(r['document_name'], _NAME_W):<{_NAME_W}}  "
                  f"{_truncate(r['document_type'], 10):<10}  "
                  f"{_truncate(r['extraction_method'], 12):<12}  "
                  f"{_truncate(r['extraction_confidence'], 6):<6}  "
                  f"{_status(r):<12}  {r['db_chunks']:>4}  {vec:>4}")
    print()

    # --- Chroma totals -----------------------------------------------------
    if chroma_err:
        print(f"Chroma vectors: {chroma_err}")
    else:
        tagged_total = sum(per_doc.values())
        untagged_total = sum(untagged.values())
        print(f"Chroma vectors: {total_vec} total")
        print(f"  - {tagged_total} tagged to {len(per_doc)} uploaded document(s)")
        if untagged:
            src_list = ", ".join(_truncate(s, 40) for s in list(untagged)[:6])
            more = "" if len(untagged) <= 6 else f", +{len(untagged) - 6} more"
            print(f"  - {untagged_total} untagged (full-corpus build) across "
                  f"{len(untagged)} source(s): {src_list}{more}")
    print()

    # --- Consistency check -------------------------------------------------
    if not db_err and docs and not chroma_err:
        print("Consistency (DB chunks vs Chroma vectors):")
        warnings = 0
        for r in docs:
            did = r["document_id"]
            db_n, vec_n = r["db_chunks"], per_doc.get(did, 0)
            if _status(r) != "active":
                print(f"  [--]  doc {did}: {_status(r)}, not indexed ({db_n}/{vec_n})")
            elif db_n == vec_n and db_n > 0:
                print(f"  [OK]  doc {did}: {db_n} DB chunks == {vec_n} vectors")
            else:
                warnings += 1
                print(f"  [WARN] doc {did}: {db_n} DB chunks but {vec_n} vectors "
                      f"(out of sync — delete + re-upload, or rebuild the index)")
        print()
        print("All consistent." if warnings == 0 else f"{warnings} document(s) out of sync.")


if __name__ == "__main__":
    main()
