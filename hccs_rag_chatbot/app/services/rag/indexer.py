"""Incremental indexing of a single document into the RAG vector store.

rag_engine.run_rag_pipeline builds the whole corpus when the store is empty.
This module adds (or removes) ONE document's chunks on the fly so an admin
upload becomes searchable without a full rebuild. It uses the same embedding
configuration and the same chunk_and_clean logic as the full build, so vectors
land in the same space.

Chunks are tagged with the owning document_id in their Chroma metadata and
given deterministic vector ids (``doc<ID>-chunk<N>``) so a document can later be
removed or replaced cleanly.
"""

import time

import app.services._engine_bootstrap  # noqa: F401  (loads .env + bridges API key)
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.config import settings
from app.services.rag.chunking import chunk_and_clean
from app.services.rag.rag_engine import RetryingGoogleGenerativeAIEmbeddings


def get_vectorstore() -> Chroma:
    """Open the persistent Chroma store with the same embeddings the RAG build
    uses (gemini-embedding-001, task_type=None) so doc and query vectors match."""
    embeddings = RetryingGoogleGenerativeAIEmbeddings(
        model=settings.EMBEDDING_MODEL, task_type=None
    )
    return Chroma(
        persist_directory=settings.CHROMA_DB_PATH,
        embedding_function=embeddings,
    )


def index_document_text(text, *, document_id, source, vectorstore=None):
    """Chunk, clean, embed ``text`` and add it to the store.

    Each chunk is tagged with document_id + source metadata. Returns a list of
    (vector_id, chunk_text) for the chunks that were successfully added. Adds one
    chunk at a time (mirroring the full build) so a single embedding failure --
    e.g. a Google safety filter -- skips just that chunk instead of the document.
    """
    vs = vectorstore or get_vectorstore()
    base = Document(
        page_content=text, metadata={"source": source, "document_id": document_id}
    )
    splits = chunk_and_clean([base])

    added = []
    for i, split in enumerate(splits):
        split.metadata["document_id"] = document_id
        split.metadata["source"] = source
        vector_id = f"doc{document_id}-chunk{i}"
        try:
            vs.add_documents([split], ids=[vector_id])
            added.append((vector_id, split.page_content))
        except IndexError:
            print(f"[indexer] skipped chunk {i} (Google safety filter).")
        except Exception as exc:
            print(f"[indexer] skipped chunk {i}: {exc!r}")
        time.sleep(0.5)
    return added


def remove_document(document_id, vectorstore=None) -> None:
    """Delete every chunk belonging to ``document_id`` from the store."""
    vs = vectorstore or get_vectorstore()
    try:
        vs._collection.delete(where={"document_id": document_id})
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[indexer] failed to delete chunks for document {document_id}: {exc!r}")
