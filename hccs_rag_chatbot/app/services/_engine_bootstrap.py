"""Shared bootstrap so the FastAPI app can reuse the original engines.

The RAG and clustering logic live in the top-level `src/` package (one directory
above hccs_rag_chatbot/). This module:
  1. Puts the repo root on sys.path so `import src.rag_engine` works regardless
     of the current working directory.
  2. Mirrors GEMINI_API_KEY into GOOGLE_API_KEY, which is the variable the
     langchain-google-genai clients actually read.

Import this module (for its side effects) before importing anything from `src`.
"""

import os
import sys

from app.core.config import settings, REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# langchain_google_genai looks for GOOGLE_API_KEY; the project's .env uses
# GEMINI_API_KEY. Bridge them so the engines authenticate without changes.
if settings.GEMINI_API_KEY and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY
