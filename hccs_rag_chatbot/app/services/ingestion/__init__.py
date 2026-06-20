"""Document ingestion: tiered text extraction (native -> OCR -> LLM cleanup)
with a confidence verdict, for building a robust corpus from arbitrary uploads.
"""

from app.services.ingestion.pipeline import IngestionResult, ingest_document

__all__ = ["IngestionResult", "ingest_document"]
