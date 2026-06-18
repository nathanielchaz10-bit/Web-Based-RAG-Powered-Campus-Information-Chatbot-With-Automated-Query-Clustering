"""Shared bootstrap for the RAG/clustering engines.

The langchain-google-genai clients read GOOGLE_API_KEY, but the project's .env
uses GEMINI_API_KEY. This module mirrors one into the other so the engines
authenticate without any code change.

Import this module (for its side effect) before instantiating a
langchain-google-genai client.
"""

import os

from dotenv import load_dotenv

from app.core.config import settings

# Load .env into the process environment the same way the RAG engine does
# (searches the CWD upward), so the clustering path -- which never imports the
# RAG engine -- gets the key regardless of whether .env sits at the repo root or
# inside hccs_rag_chatbot/. This is what makes chat work; mirror it here.
load_dotenv()

# langchain_google_genai accepts GOOGLE_API_KEY or GEMINI_API_KEY from the
# environment, while the project's .env uses GEMINI_API_KEY. Source the key from
# pydantic settings (which reads .env) or whatever load_dotenv populated, then
# make sure BOTH env var names are set so any client variant authenticates.
_api_key = (
    settings.GEMINI_API_KEY
    or os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
)
if _api_key:
    os.environ.setdefault("GOOGLE_API_KEY", _api_key)
    os.environ.setdefault("GEMINI_API_KEY", _api_key)
