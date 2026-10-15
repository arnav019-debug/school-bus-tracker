from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models.profile import Profile
from app.models.device_token import DeviceToken
from app.models.notification_log import NotificationLog
from app.schemas.notification import (
    DeviceTokenRegister,
    DeviceTokenUnregister,
    DeviceTokenResponse,
    NotificationLogResponse,
)
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register-token", response_model=DeviceTokenResponse)
@router.post("/register-token/", response_model=DeviceTokenResponse, include_in_schema=False)
async def register_device_token(
    payload: DeviceTokenRegister,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Register or update an FCM push notification token for the current user.
    If the token is already registered to this or another user, it updates ownership.
    """
    clean_token = payload.token.strip()
    if not clean_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token cannot be empty")

    res = await db.execute(select(DeviceToken).where(DeviceToken.token == clean_token))
    existing = res.scalars().first()

    now_utc = datetime.now(timezone.utc)
    if existing:
        existing.user_id = str(current_user.id)
        existing.platform = payload.platform or "android"
        existing.updated_at = now_utc
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        new_token = DeviceToken(
            user_id=str(current_user.id),
            token=clean_token,
            platform=payload.platform or "android",
            created_at=now_utc,
            updated_at=now_utc
        )
        db.add(new_token)
        await db.commit()
        await db.refresh(new_token)
        return new_token

@router.post("/unregister-token", status_code=status.HTTP_204_NO_CONTENT)
@router.post("/unregister-token/", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def unregister_device_token(
    payload: DeviceTokenUnregister,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Unregister a push notification token for the current user.
    """
    clean_token = payload.token.strip()
    res = await db.execute(
        select(DeviceToken).where(
            DeviceToken.token == clean_token,
            DeviceToken.user_id == str(current_user.id)
        )
    )
    existing = res.scalars().first()
    if existing:
        await db.delete(existing)
        await db.commit()
    return None

@router.get("/logs", response_model=List[NotificationLogResponse])
@router.get("/logs/", response_model=List[NotificationLogResponse], include_in_schema=False)
async def get_notification_logs(
    user_id: Optional[str] = Query(None, description="Filter by user ID (admins only)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    List notification history logs.
    - Non-admins can only view their own logs.
    - Admins can view all logs or filter by user_id.
    """
    query = select(NotificationLog)

    if current_user.role != "admin":
        query = query.where(NotificationLog.user_id == str(current_user.id))
    elif user_id:
        query = query.where(NotificationLog.user_id == str(user_id))

    query = query.order_by(NotificationLog.sent_at.desc()).offset(skip).limit(limit)
    res = await db.execute(query)
    logs = res.scalars().all()
    return logs
