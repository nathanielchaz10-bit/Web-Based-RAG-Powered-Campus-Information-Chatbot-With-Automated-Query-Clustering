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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.chat_session import ChatSession
from app.models.chat_response import ChatResponse
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount
from app.services.rag import rag_service

router = APIRouter(prefix="/chat", tags=["Chat"])

# How many prior turns to feed back into the retriever as context.
_HISTORY_TURNS = 10


class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


class ChatResponseOut(BaseModel):
    answer: str
    sources: list[str]
    session_id: int
    query_id: int
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
    user: UserAccount = Depends(get_current_user),
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
        raise HTTPException(
            status_code=503,
            detail=f"The assistant is not available right now: {exc}",
        )

    query = QueryLog(
        query_text=message,
        session_id=session.session_id,
        timestamp=datetime.utcnow(),
        response_time_ms=result["response_time_ms"],
        is_valid=True,
    )
    db.add(query)
    db.flush()  # assign query_id

    db.add(ChatResponse(
        query_id=query.query_id,
        response_text=result["answer"],
        source_chunks=json.dumps(result["sources"]),
        generated_at=datetime.utcnow(),
    ))

    session.total_messages = (session.total_messages or 0) + 1
    session.last_activity = datetime.utcnow()
    db.commit()

    return ChatResponseOut(
        answer=result["answer"],
        sources=result["sources"],
        session_id=session.session_id,
        query_id=query.query_id,
        response_time_ms=result["response_time_ms"],
    )
