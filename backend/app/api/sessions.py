from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import User, ChatSession, ChatMessage
from app.api.deps import get_current_user
from app.schemas.session_schemas import SessionCreate, SessionOut, SessionDetailOut

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


@router.get("", response_model=List[SessionOut])
async def list_sessions(
    workspace_path: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ChatSession).where(ChatSession.user_id == current_user.id)
    if workspace_path:
        query = query.where(ChatSession.workspace_path == workspace_path)
    query = query.order_by(desc(ChatSession.updated_at))

    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=SessionOut)
async def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = ChatSession(
        user_id=current_user.id,
        title=payload.title or "New Session",
        workspace_path=payload.workspace_path,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionDetailOut)
async def get_session_detail(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .options(selectinload(ChatSession.messages))
    )
    res = await db.execute(query)
    session = res.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/workspaces/all", response_model=List[str])
async def list_user_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns all unique workspace paths this user has opened sessions in."""
    query = (
        select(ChatSession.workspace_path)
        .where(
            ChatSession.user_id == current_user.id,
            ChatSession.workspace_path.isnot(None)
        )
        .distinct()
    )
    res = await db.execute(query)
    paths = [row[0] for row in res.fetchall() if row[0]]
    return sorted(paths)