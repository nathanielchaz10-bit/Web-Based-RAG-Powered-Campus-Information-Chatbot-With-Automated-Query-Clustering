import os
import re
import time
from dotenv import load_dotenv

from app.core.config import settings

from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import MessagesPlaceholder

load_dotenv()

# Google's embedding API occasionally returns transient server-side errors
# (500 INTERNAL, 503 UNAVAILABLE, 429 rate limits, deadline exceeded). These are
# not caused by our data or query -- a retry almost always succeeds. Without
# retries a single blip fails the whole chat turn (surfaced to the user as 503).
_TRANSIENT_MARKERS = (
    "500", "internal",
    "503", "unavailable",
    "429", "resource_exhausted", "rate limit", "quota",
    "deadline", "timeout", "timed out",
)


def _is_transient_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def _log_retry(retry_state):
    exc = retry_state.outcome.exception()
    print(f"[embedding retry] attempt {retry_state.attempt_number} failed: {exc!r} — retrying...")


# Retry a few times with exponential backoff (2s, 4s, 8s, capped at 10s).
_embedding_retry = retry(
    retry=retry_if_exception(_is_transient_error),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    stop=stop_after_attempt(4),
    before_sleep=_log_retry,
    reraise=True,
)


class RetryingGoogleGenerativeAIEmbeddings(GoogleGenerativeAIEmbeddings):
    """GoogleGenerativeAIEmbeddings that retries on transient API errors."""

    @_embedding_retry
    def embed_query(self, text):
        return super().embed_query(text)

    @_embedding_retry
    def embed_documents(self, texts, *args, **kwargs):
        return super().embed_documents(texts, *args, **kwargs)


class HistoryAwareRagChain:
    """Two-step RAG chain that keeps the question-rewrite LLM call separate
    from the retrieval (embedding) call.

    LangChain's create_history_aware_retriever nests the rewrite LLM call and
    the embedding call inside a single runnable invocation. With the Gemini
    google-genai client, making the embedding request immediately after the
    gemini-2.5-flash call in that nested context reliably triggers a spurious
    500 INTERNAL from the embedding API (the identical query embeds fine on its
    own). Running the rewrite as its own fully-completed invocation first, then
    the plain retrieval chain, avoids that interaction.
    """

    def __init__(self, contextualize_chain, retrieval_chain):
        self._contextualize = contextualize_chain
        self._retrieval = retrieval_chain

    def invoke(self, payload, *args, **kwargs):
        question = payload["input"]
        history = payload.get("chat_history") or []

        if history:
            # Resolve the standalone question FIRST (separate LLM call that
            # fully returns before any embedding request is made).
            standalone = self._contextualize.invoke(
                {"input": question, "chat_history": history}
            )
            standalone = (standalone or "").strip() or question
        else:
            standalone = question

        return self._retrieval.invoke(
            {"input": standalone, "chat_history": history}, *args, **kwargs
        )


def load_documents_from_folder(folder_path):
    documents = []
    # Walk recursively so the per-type subfolders (docs/, pdf/, txt/) under the
    # uploads directory are all picked up regardless of which one a file lands in.
    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)

            if file.endswith(".pdf"):
                print(f"Loading PDF: {file}")
                loader = PyPDFLoader(file_path)
                documents.extend(loader.load())

            elif file.endswith(".docx"):
                print(f"Loading DOCX: {file}")
                loader = Docx2txtLoader(file_path)
                documents.extend(loader.load())

            elif file.endswith(".txt"):
                print(f"Loading TXT: {file}")
                loader = TextLoader(file_path, encoding="utf-8")
                documents.extend(loader.load())

    return documents

def run_rag_pipeline():

    print()
    print("Starting RAG pipeline.")

    # chroma_db/ and the uploads/ source documents are resolved via app config
    # so this works no matter where the engine module physically sits.
    chroma_db_path = settings.CHROMA_DB_PATH
    docs_path = settings.UPLOADS_PATH

    # set up the embedding model (with automatic retries on transient API errors)
    embeddings = RetryingGoogleGenerativeAIEmbeddings(model="gemini-embedding-001", task_type=None)

    # Always open (or create) the persistent store first, then decide whether it
    # actually needs building. A directory existing on disk does NOT mean it holds
    # a real index -- a stray placeholder file (or an interrupted earlier build)
    # leaves an empty collection that an existence-only check would happily load,
    # making every answer "I do not know" because retrieval returns nothing. So we
    # check the collection's document count, not just the folder.
    vectorstore = Chroma(
        persist_directory=chroma_db_path,
        embedding_function=embeddings
    )

    try:
        existing_count = vectorstore._collection.count()
    except Exception:
        existing_count = 0

    if existing_count > 0:
        print()
        print(f"Found existing database with {existing_count} chunks. Loading from disk.")

    else:
        print()
        print("No populated database found. Building from scratch.")

        # 1. load documents (uploads/ folder, incl. docs/ pdf/ txt/ subfolders)
        docs = load_documents_from_folder(docs_path)
        if not docs:
            print()
            print("Error 404: Please put a PDF, DOCX or TXT file in the 'uploads' folder.")
            return

        # 2. chunk the documents
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        
        # 3. filterng the chunks to remove garbage formatting
        # skipped to since lilinisin din natin mismong docs, JIC lang to
        
        cleaned_splits = []
        for split in splits:
            # removing hidden Word doc formatting codes and null characters
            clean_text = split.page_content.replace('\x00', '').replace('\xa0', ' ')
            
            # collapse spacing and empty line breaks into a single space
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            # if chunk has less than 15 valid characters, its garbage formatting.
            if len(clean_text) > 15:
                split.page_content = clean_text
                cleaned_splits.append(split)
                
        splits = cleaned_splits

        print()
        print(f"Total chunks to process for ChromaDB: {len(splits)}")
        print()

        successful_chunks = 0
        for i, split in enumerate(splits):
            try:
                # sends ONE document only. 
                vectorstore.add_documents([split])
                successful_chunks += 1
                
                # print progress every 50 chunks para sure di nagcrash
                if (i + 1) % 50 == 0:
                    print(f"Processed {i + 1}/{len(splits)}.")
                    
            except IndexError:
                print()
                print(f"Skipped chunk {i+1} (Google Safety Filter triggered, likely a disciplinary rule)")
            except Exception as e:
                print()
                print(f"Skipped chunk {i+1} due to an unknown API error.")
            
            time.sleep(0.5) 

        print()    
        print(f"Successfully embedded {successful_chunks}/{len(splits)} chunks.")

    # 5. set up retriever
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # 6. set up the LLM and prompt
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    # para matandaan ng AI previous messages and use them as context, need to "contextualize" the question first.
    # prompt para sa AI mismo
    contextualize_q_system_prompt = (
        "Given a chat history and the latest user question "
        "which might reference context in the chat history, "
        "formulate a standalone question which can be understood "
        "without the chat history. Do NOT answer the question, "
        "just reformulate it if needed and otherwise return it as is."
    )
    # prompt para sa user input + chat history
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    # Rewrite step as its OWN chain (LLM only -- no embedding nested inside).
    contextualize_chain = contextualize_q_prompt | llm | StrOutputParser()

    # 7. build chains
    qa_system_prompt = (
        "You are a helpful assistant for Holy Child Catholic School students. "
        "Use the following pieces of retrieved context to answer the question. "
        "If you do not know the answer based on the context, say that you do not know. "
        "Context: {context}"
    )

    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    # Plain retriever (NOT history-aware): the question is already rewritten by
    # contextualize_chain before this runs, so no LLM call is nested with the
    # embedding call here.
    retrieval_chain = create_retrieval_chain(retriever, question_answer_chain)

    rag_chain = HistoryAwareRagChain(contextualize_chain, retrieval_chain)

    print("RAG Chain Loaded Successfully.")
    return rag_chain