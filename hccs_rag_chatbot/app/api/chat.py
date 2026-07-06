"""Student chat endpoint backed by the real RAG engine.

Each turn is persisted to the relational schema:
  ChatSession  (one per conversation)
  QueryLog     (the student's question + timing)
  ChatResponse (the AI answer + source citations)
The conversation is reconstructed server-side from prior turns so the retriever
stays history-aware without trusting client-supplied history.
"""

import json
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import enforce_chat_rate_limit, enforce_guest_rate_limit, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.chat_session import ChatSession
from app.models.chat_response import ChatResponse
from app.models.document import Document
from app.models.document_retrieval import DocumentRetrieval
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount
from app.services.rag import rag_service
# Lightweight, local (zero-API-cost) NLP enrichment. These modules import
# cleanly even if their optional dependency (vaderSentiment) is missing.
from app.services.nlp.sentiment import classify_sentiment
from app.services.nlp.intent import classify_intent

router = APIRouter(prefix="/chat", tags=["Chat"])

# How many prior turns to feed back into the retriever as context.
_HISTORY_TURNS = 10


def _classify(message: str) -> tuple[str | None, str | None]:
    """Run local sentiment + intent classification, never raising.

    Enrichment is a nice-to-have stored alongside each QueryLog; if it fails
    for any reason it must not break the student's chat turn, so we swallow
    errors and fall back to None (column stays NULL).
    """
    try:
        return classify_sentiment(message), classify_intent(message)
    except Exception:  # pragma: no cover - defensive; classifiers are pure
        return None, None


class ChatRequest(BaseModel):
    # max_length bounds per-turn Gemini cost + DB storage; the handler's strip()
    # check still owns the empty-message case (422 vs the nicer 400).
    message: str = Field(max_length=2000)
    session_id: int | None = None


class ChatResponseOut(BaseModel):
    answer: str
    sources: list[str]
    session_id: int
    query_id: int
    response_time_ms: int


class GuestChatRequest(BaseModel):
    message: str = Field(max_length=2000)


class GuestChatResponseOut(BaseModel):
    answer: str
    sources: list[str]
    response_time_ms: int


def _get_or_create_session(db: Session, user: UserAccount, session_id: int | None) -> ChatSession:
    if session_id is not None:
        session = (
            db.query(ChatSession)
            .filter_by(session_id=session_id, user_id=user.user_id)
            .first()
        )
        if session:
            return session
    session = ChatSession(user_id=user.user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _build_history(db: Session, session: ChatSession) -> list[tuple[str, str]]:
    """Reconstruct (human, ai) pairs from the last few turns of this session."""
    recent = (
        db.query(QueryLog)
        .filter_by(session_id=session.session_id)
        .order_by(QueryLog.query_id.desc())
        .limit(_HISTORY_TURNS)
        .all()
    )
    history: list[tuple[str, str]] = []
    for q in reversed(recent):  # oldest first
        history.append(("human", q.query_text))
        if q.response and q.response.response_text:
            history.append(("ai", q.response.response_text))
    return history


@router.post("", response_model=ChatResponseOut)
@router.post("/", response_model=ChatResponseOut)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(enforce_chat_rate_limit),
):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session = _get_or_create_session(db, user, payload.session_id)
    history = _build_history(db, session)

    try:
        result = rag_service.answer_query(message, history)
    except Exception as exc:
        # Print the FULL traceback to the server console so we can see the real
        # root cause (not just the short message the user sees).
        print("\n=== /chat failed — full traceback ===")
        traceback.print_exc()
        print(f"history turns fed to retriever: {len(history)}")
        print("=== end traceback ===\n")
        # Most likely: missing GEMINI_API_KEY or no documents to index yet.
        # Keep the real cause in the server log above; never leak {exc} (paths,
        # keys, internals) to the client.
        raise HTTPException(
            status_code=503,
            detail="The assistant is not available right now. Please try again in a moment.",
        )

    sentiment, detected_intent = _classify(message)

    # The chain rewrites follow-ups into a self-contained question; persist it
    # only when it actually differs from what the student typed, so first-turn
    # rows stay NULL and clustering can COALESCE back to query_text.
    resolved = (result.get("resolved_question") or "").strip()
    resolved_query_text = resolved if resolved and resolved != message else None

    query = QueryLog(
        query_text=message,
        resolved_query_text=resolved_query_text,
        session_id=session.session_id,
        timestamp=datetime.utcnow(),
        response_time_ms=result["response_time_ms"],
        is_valid=True,
        sentiment=sentiment,
        detected_intent=detected_intent,
    )
    db.add(query)
    db.flush()  # assign query_id

    db.add(ChatResponse(
        query_id=query.query_id,
        response_text=result["answer"],
        source_chunks=json.dumps(result["sources"]),
        is_fallback=result.get("is_fallback", False),
        generated_at=datetime.utcnow(),
    ))

    session.total_messages = (session.total_messages or 0) + 1
    session.last_activity = datetime.utcnow()

    # Usage analytics: one retrieval event per document whose chunks helped
    # answer this question (drives the Document Directory's "retrievals this
    # month"). Best-effort -- it must never break the chat turn, and we only log
    # ids that still exist so a stale id can't FK-abort the commit.
    try:
        retrieved_ids = result.get("retrieved_document_ids") or []
        if retrieved_ids:
            valid_ids = {
                row[0]
                for row in db.query(Document.document_id)
                .filter(Document.document_id.in_(retrieved_ids))
                .all()
            }
            now = datetime.utcnow()
            for did in valid_ids:
                db.add(DocumentRetrieval(document_id=did, retrieved_at=now))
    except Exception:
        pass

    db.commit()

    return ChatResponseOut(
        answer=result["answer"],
        sources=result["sources"],
        session_id=session.session_id,
        query_id=query.query_id,
        response_time_ms=result["response_time_ms"],
    )


@router.post("/guest", response_model=GuestChatResponseOut)
def guest_chat(
    payload: GuestChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(enforce_guest_rate_limit),
):
    """Anonymous chat for visitors without an @hccs.edu.ph account.

    Restricted to the guest-visible document categories (see
    settings.guest_document_types) via a metadata-filtered retrieval, and
    stateless -- no ChatSession, so guests share no history. The turn is still
    logged to QueryLog (session_id NULL) so it counts toward the daily budget cap
    and feeds the dashboards/clustering like any other query.
    """
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    allowed_ids = [
        row[0]
        for row in db.query(Document.document_id)
        .filter(
            Document.is_active.is_(True),
            Document.document_type.in_(settings.guest_document_types),
        )
        .all()
    ]

    try:
        result = rag_service.answer_query_restricted(message, allowed_ids)
    except Exception as exc:
        print("\n=== /chat/guest failed — full traceback ===")
        traceback.print_exc()
        print("=== end traceback ===\n")
        raise HTTPException(
            status_code=503,
            detail="The assistant is not available right now. Please try again in a moment.",
        )

    sentiment, detected_intent = _classify(message)

    query = QueryLog(
        query_text=message,
        session_id=None,  # anonymous guest: no session
        timestamp=datetime.utcnow(),
        response_time_ms=result["response_time_ms"],
        is_valid=True,
        sentiment=sentiment,
        detected_intent=detected_intent,
    )
    db.add(query)
    db.flush()

    db.add(ChatResponse(
        query_id=query.query_id,
        response_text=result["answer"],
        source_chunks=json.dumps(result["sources"]),
        is_fallback=result.get("is_fallback", False),
        generated_at=datetime.utcnow(),
    ))

    # Same best-effort document-usage logging as the authenticated path.
    try:
        retrieved_ids = result.get("retrieved_document_ids") or []
        if retrieved_ids:
            valid_ids = {
                row[0]
                for row in db.query(Document.document_id)
                .filter(Document.document_id.in_(retrieved_ids))
                .all()
            }
            now = datetime.utcnow()
            for did in valid_ids:
                db.add(DocumentRetrieval(document_id=did, retrieved_at=now))
    except Exception:
        pass

    db.commit()

    return GuestChatResponseOut(
        answer=result["answer"],
        sources=result["sources"],
        response_time_ms=result["response_time_ms"],
    )


# === NEW ENDPOINT: Initialize a fresh session ===
@router.post("/sessions/new")
def create_new_session(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user)
):
    """Explicitly create a new session record."""
    session = ChatSession(user_id=user.user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.session_id}


@router.get("/sessions")
def get_user_sessions(
        db: Session = Depends(get_db),
        user: UserAccount = Depends(get_current_user)
):
    """Retrieve all chat sessions for the authenticated user."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.user_id)
        .order_by(ChatSession.last_activity.desc())
        .all()
    )

    result = []
    for s in sessions:
        # Get the first query of the session to use as a title
        first_query = (
            db.query(QueryLog)
            .filter(QueryLog.session_id == s.session_id)
            .order_by(QueryLog.timestamp.asc())
            .first()
        )

        # Fallback to "New Conversation" if there are no messages yet
        title = first_query.query_text[:30] + "..." if (first_query and len(first_query.query_text) > 30) else (first_query.query_text if first_query else "New Conversation")

        result.append({
            "session_id": s.session_id,
            "title": title,
            "last_activity": s.last_activity.isoformat()
        })
    return result


@router.get("/sessions/{session_id}/history")
def get_session_history(
        session_id: int,
        db: Session = Depends(get_db),
        user: UserAccount = Depends(get_current_user)
):
    """Retrieve the full turn history for a specific session."""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id,
        ChatSession.user_id == user.user_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or access denied.")

    queries = (
        db.query(QueryLog)
        .filter(QueryLog.session_id == session_id)
        .order_by(QueryLog.timestamp.asc())
        .all()
    )

    history = []
    for q in queries:
        # Add the user's query
        history.append({
            "role": "user",
            "content": q.query_text
        })
        # Add the bot's response if it exists
        if q.response:
            history.append({
                "role": "bot",
                "content": q.response.response_text,
                "sources": json.loads(q.response.source_chunks) if q.response.source_chunks else []
            })
    return history


@router.delete("/sessions/{session_id}")
def delete_session(
        session_id: int,
        db: Session = Depends(get_db),
        user: UserAccount = Depends(get_current_user)
):
    """Delete a specific chat session and its history."""
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id,
        ChatSession.user_id == user.user_id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()

    return {"status": "success", "message": "Session deleted"}


# === Settings → Privacy & Data ===

@router.delete("/sessions")
def delete_all_sessions(
        db: Session = Depends(get_db),
        user: UserAccount = Depends(get_current_user)
):
    """Permanently delete every chat session (and their queries/responses)
    belonging to the current user. Backs the "Clear all chat history" button
    in Settings → Privacy & Data.

    Uses db.delete() per-row (not a bulk query.delete()) so SQLAlchemy's ORM
    cascades fire and QueryLog/ChatResponse rows are cleaned up too, same as
    the single-session delete above.
    """
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user.user_id).all()
    count = len(sessions)
    for session in sessions:
        db.delete(session)
    db.commit()

    return {"status": "success", "deleted_count": count}


@router.get("/export")
def export_my_chats(
        db: Session = Depends(get_db),
        user: UserAccount = Depends(get_current_user)
):
    """Return every conversation the current user has had, as JSON, for the
    "Export my chats" button in Settings → Privacy & Data. The frontend turns
    this straight into a downloadable file -- no PII beyond the user's own
    email is included.
    """
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.user_id)
        .order_by(ChatSession.created_at.asc())
        .all()
    )

    exported_sessions = []
    for session in sessions:
        queries = (
            db.query(QueryLog)
            .filter(QueryLog.session_id == session.session_id)
            .order_by(QueryLog.timestamp.asc())
            .all()
        )

        messages = []
        for q in queries:
            messages.append({
                "role": "user",
                "content": q.query_text,
                "timestamp": q.timestamp.isoformat() if q.timestamp else None,
            })
            if q.response:
                messages.append({
                    "role": "bot",
                    "content": q.response.response_text,
                    "sources": json.loads(q.response.source_chunks) if q.response.source_chunks else [],
                    "timestamp": q.response.generated_at.isoformat() if q.response.generated_at else None,
                })

        exported_sessions.append({
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "messages": messages,
        })

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "user_email": user.email,
        "sessions": exported_sessions,
    }
