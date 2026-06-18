"""Shared bootstrap for the RAG/clustering engines.

The langchain-google-genai clients read GOOGLE_API_KEY, but the project's .env
uses GEMINI_API_KEY. This module mirrors one into the other so the engines
authenticate without any code change.

Import this module (for its side effect) before instantiating a
langchain-google-genai client.
"""

import os

from app.core.config import settings

# langchain_google_genai looks for GOOGLE_API_KEY; the project's .env uses
# GEMINI_API_KEY. Bridge them so the engines authenticate without changes.
if settings.GEMINI_API_KEY and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY
