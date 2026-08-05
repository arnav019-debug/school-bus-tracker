from typing import AsyncGenerator, Optional
import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models.profile import Profile
from app.schemas.auth import TokenData
from app.services.auth_service import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Profile:
    """
    Dependency that decodes the JWT access token and returns the current user Profile.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: Optional[str] = payload.get("sub") or payload.get("user_id")
    email: Optional[str] = payload.get("email")

    if user_id is None and email is None:
        raise credentials_exception
        
    # Query Profile from DB
    query = select(Profile)
    if user_id:
        try:
            query = query.where(Profile.id == uuid.UUID(user_id))
        except ValueError:
            query = query.where(Profile.id == user_id)
    elif email:
        query = query.where(Profile.email == email)
        
    result = await db.execute(query)
    profile = result.scalars().first()
    
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
        
    return profile

async def get_current_admin(
    current_user: Profile = Depends(get_current_user)
) -> Profile:
    """
    Dependency requiring admin or staff role.
    """
    if current_user.role not in ["admin", "staff"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return current_user
