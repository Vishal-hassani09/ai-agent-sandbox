from typing import Optional
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.session import get_db
from app.db.models import User

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticates user via X-Auth-Token (local/Cloud Shell safe) or Authorization: Bearer (production)."""
    raw_token: Optional[str] = None

    if x_auth_token:
        raw_token = x_auth_token.replace("Bearer ", "").strip()
    elif credentials and credentials.credentials:
        raw_token = credentials.credentials.strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Missing X-Auth-Token or Authorization header.",
        )

    decoded = decode_access_token(raw_token)
    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
        )

    email = decoded.get("email") or decoded.get("sub") if isinstance(decoded, dict) else str(decoded)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing user identifier.",
        )

    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user