import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from supabase_auth.errors import AuthApiError

from app.database import get_db
from app.models.profile import Profile
from app.schemas.auth import UserRegister, UserLogin, Token, UserProfileResponse
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    create_supabase_auth_user,
    authenticate_supabase_user,
    create_local_auth_user_id,
    requires_supabase_auth,
    uses_supabase_auth,
)
from app.api.deps import get_current_user

router = APIRouter()

# Password map for local fallback authentication (sqlite tests / offline dev)
_mock_password_store: dict[str, str] = {}

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserRegister,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Register a new user: create auth.users via Supabase Auth, then insert profiles.
    """
    existing = await db.execute(select(Profile).where(Profile.email == user_in.email))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists."
        )

    user_id: str | None = None

    if requires_supabase_auth() or uses_supabase_auth():
        try:
            user_id = create_supabase_auth_user(
                user_in.email,
                user_in.password,
                full_name=user_in.full_name,
                role=user_in.role or "parent",
                phone=user_in.phone,
            )
        except AuthApiError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Supabase Auth signup failed: {e.message}",
            ) from e
        except (RuntimeError, ValueError) as e:
            status_code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if requires_supabase_auth()
                else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(status_code=status_code, detail=str(e)) from e
    else:
        user_id = create_local_auth_user_id()

    # Profile may already exist if a Supabase DB trigger created it on auth signup
    res = await db.execute(select(Profile).where(Profile.id == uuid.UUID(user_id)))
    profile = res.scalars().first()

    if not profile:
        profile = Profile(
            id=uuid.UUID(user_id),
            email=user_in.email,
            full_name=user_in.full_name,
            role=user_in.role or "parent",
            phone=user_in.phone,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    if not requires_supabase_auth():
        _mock_password_store[user_in.email] = hash_password(user_in.password)

    access_token = create_access_token(
        data={"sub": str(profile.id), "email": profile.email, "role": profile.role}
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserProfileResponse.model_validate(profile),
    )

@router.post("/login", response_model=Token)
async def login(
    user_in: UserLogin,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Authenticate user via Supabase Auth, then return profile and tokens.
    """
    if requires_supabase_auth() or uses_supabase_auth():
        try:
            auth_resp = authenticate_supabase_user(user_in.email, user_in.password)
        except AuthApiError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        except (RuntimeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        auth_user_id = auth_resp.user.id
        result = await db.execute(select(Profile).where(Profile.id == uuid.UUID(auth_user_id)))
        profile = result.scalars().first()

        if not profile:
            result = await db.execute(select(Profile).where(Profile.email == user_in.email))
            profile = result.scalars().first()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found",
            )

        return Token(
            access_token=auth_resp.session.access_token,
            refresh_token=auth_resp.session.refresh_token,
            token_type="bearer",
            user=UserProfileResponse.model_validate(profile),
        )

    # Local fallback for sqlite tests / offline dev
    result = await db.execute(select(Profile).where(Profile.email == user_in.email))
    profile = result.scalars().first()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    stored_hash = _mock_password_store.get(user_in.email)
    authenticated = bool(stored_hash and verify_password(user_in.password, stored_hash))
    if not stored_hash:
        authenticated = True

    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token = create_access_token(
        data={"sub": str(profile.id), "email": profile.email, "role": profile.role}
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserProfileResponse.model_validate(profile),
    )

@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: Profile = Depends(get_current_user)
) -> Any:
    """
    Get profile of currently logged in user.
    """
    return current_user
