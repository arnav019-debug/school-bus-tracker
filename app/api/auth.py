import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from supabase_auth.errors import AuthApiError

from app.database import get_db
from app.models.profile import Profile
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    Token,
    UserProfileResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_supabase_auth_user,
    authenticate_supabase_user,
    create_local_auth_user_id,
    send_supabase_password_reset,
    update_supabase_user_password,
    requires_supabase_auth,
    uses_supabase_auth,
)
from app.services.rate_limiter import forgot_password_limiter, reset_password_limiter
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
        if not settings.is_local_auth_allowed():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Production requires Supabase authentication. Local authentication is disabled.",
            )
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

from fastapi.responses import HTMLResponse
from app.config import settings
from app.services.rate_limiter import (
    forgot_password_limiter,
    reset_password_limiter,
    login_limiter,
    login_failed_limiter,
    get_client_ip,
)
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_supabase_auth_user,
    authenticate_supabase_user,
    create_local_auth_user_id,
    send_supabase_password_reset,
    update_supabase_user_password,
    verify_supabase_recovery_token,
    requires_supabase_auth,
    uses_supabase_auth,
)

RESET_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password — School Bus Tracker</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #F8FAFC;
      color: #1E293B;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 16px;
    }
    .card {
      background: #FFFFFF;
      border-radius: 16px;
      box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
      width: 100%;
      max-width: 440px;
      padding: 32px 28px;
    }
    .header {
      text-align: center;
      margin-bottom: 24px;
    }
    .title {
      font-size: 22px;
      font-weight: 700;
      color: #0F172A;
      margin-bottom: 8px;
    }
    .subtitle {
      font-size: 14px;
      color: #64748B;
    }
    .form-group {
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #334155;
      margin-bottom: 6px;
    }
    input[type="password"] {
      width: 100%;
      padding: 12px 14px;
      border: 1px solid #CBD5E1;
      border-radius: 8px;
      font-size: 15px;
      outline: none;
      transition: border-color 0.15s ease;
    }
    input[type="password"]:focus {
      border-color: #2563EB;
      box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
    }
    .btn {
      width: 100%;
      padding: 13px;
      background-color: #2563EB;
      color: #FFFFFF;
      border: none;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.15s ease;
      margin-top: 8px;
    }
    .btn:hover { background-color: #1D4ED8; }
    .btn:disabled { background-color: #94A3B8; cursor: not-allowed; }
    .alert {
      padding: 12px 14px;
      border-radius: 8px;
      font-size: 14px;
      margin-bottom: 16px;
      display: none;
    }
    .alert-error {
      background-color: #FEF2F2;
      color: #991B1B;
      border: 1px solid #F87171;
    }
    .alert-success {
      background-color: #F0FDF4;
      color: #166534;
      border: 1px solid #86EFAC;
    }
    .requirements {
      font-size: 12px;
      color: #64748B;
      margin-top: 6px;
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1 class="title">School Bus Tracker</h1>
      <p class="subtitle">Enter your new secure password below</p>
    </div>

    <div id="alertBox" class="alert"></div>

    <div id="tokenMissingNotice" style="display: none;">
      <p style="font-size: 14px; color: #DC2626; text-align: center; margin-bottom: 16px;">
        Invalid or expired reset link. Please request a new password reset link from the School Bus Tracker app.
      </p>
    </div>

    <form id="resetForm">
      <div class="form-group">
        <label for="newPassword">New Password</label>
        <input type="password" id="newPassword" required autocomplete="new-password" placeholder="At least 8 characters">
        <div class="requirements">
          Must be at least 8 characters with uppercase, lowercase, digit, and special character.
        </div>
      </div>

      <div class="form-group">
        <label for="confirmPassword">Confirm New Password</label>
        <input type="password" id="confirmPassword" required autocomplete="new-password" placeholder="Re-enter new password">
      </div>

      <button type="submit" id="submitBtn" class="btn">Update Password</button>
    </form>
  </div>

  <script>
    (function() {
      // 1. Read token from URL hash or query params
      var token = null;
      var hash = window.location.hash ? window.location.hash.substring(1) : "";
      if (hash) {
        var params = new URLSearchParams(hash);
        token = params.get("access_token") || params.get("token");
      }
      if (!token) {
        var urlParams = new URLSearchParams(window.location.search);
        token = urlParams.get("token") || urlParams.get("access_token");
      }

      // 2. Immediately strip token from browser URL and history
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, document.title, window.location.pathname);
      }

      var alertBox = document.getElementById("alertBox");
      var resetForm = document.getElementById("resetForm");
      var tokenNotice = document.getElementById("tokenMissingNotice");
      var submitBtn = document.getElementById("submitBtn");

      if (!token) {
        resetForm.style.display = "none";
        tokenNotice.style.display = "block";
        return;
      }

      function showAlert(msg, isSuccess) {
        alertBox.textContent = msg;
        alertBox.className = "alert " + (isSuccess ? "alert-success" : "alert-error");
        alertBox.style.display = "block";
      }

      resetForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var pwd = document.getElementById("newPassword").value;
        var confirmPwd = document.getElementById("confirmPassword").value;

        if (pwd !== confirmPwd) {
          showAlert("Passwords do not match.", false);
          return;
        }

        if (pwd.length < 8 || !/[A-Z]/.test(pwd) || !/[a-z]/.test(pwd) || !/[0-9]/.test(pwd) || !/[!@#$%^&*(),.?":{}|<>_-]/.test(pwd)) {
          showAlert("Password does not meet complexity requirements.", false);
          return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = "Updating...";

        fetch("/api/v1/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: token, new_password: pwd })
        })
        .then(function(res) {
          return res.json().then(function(data) {
            return { ok: res.ok, status: res.status, data: data };
          });
        })
        .then(function(result) {
          if (result.ok) {
            showAlert("Password reset successfully! You can now log into the School Bus Tracker app.", true);
            resetForm.style.display = "none";
          } else {
            var detail = result.data && result.data.detail ? result.data.detail : "Failed to reset password. Please try again.";
            showAlert(detail, false);
            submitBtn.disabled = false;
            submitBtn.textContent = "Update Password";
          }
        })
        .catch(function(err) {
          showAlert("Network error occurred. Please try again.", false);
          submitBtn.disabled = false;
          submitBtn.textContent = "Update Password";
        });
      });
    })();
  </script>
</body>
</html>
"""

@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_page() -> HTMLResponse:
    """
    Serves a secure HTTPS password reset completion page.
    Strict CSP, Cache-Control: no-store, no third-party scripts.
    """
    response = HTMLResponse(content=RESET_PAGE_HTML, status_code=status.HTTP_200_OK)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    user_in: UserLogin,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Authenticate user via Supabase Auth, then return profile and tokens.
    Rate-limited by IP and per-email account.
    """
    client_ip = get_client_ip(request)
    login_limiter.check(f"ip:{client_ip}")

    if requires_supabase_auth() or uses_supabase_auth():
        try:
            auth_resp = authenticate_supabase_user(user_in.email, user_in.password)
        except (AuthApiError, RuntimeError, ValueError):
            login_failed_limiter.check(f"email:{user_in.email.lower().strip()}")
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

    # Local fallback for sqlite tests / offline dev ONLY
    if not settings.is_local_auth_allowed():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Production requires Supabase authentication. Local authentication is disabled.",
        )

    result = await db.execute(select(Profile).where(Profile.email == user_in.email))
    profile = result.scalars().first()

    if not profile:
        login_failed_limiter.check(f"email:{user_in.email.lower().strip()}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    stored_hash = _mock_password_store.get(user_in.email)
    authenticated = bool(stored_hash and verify_password(user_in.password, stored_hash))
    if not stored_hash:
        authenticated = True

    if not authenticated:
        login_failed_limiter.check(f"email:{user_in.email.lower().strip()}")
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

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    req_body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Request password recovery email using implicit flow.
    Rate-limited by client IP and email bucket.
    Always returns generic response to prevent email enumeration.
    Never logs or exposes tokens.
    """
    client_ip = get_client_ip(request)
    forgot_password_limiter.check(f"ip:{client_ip}")
    forgot_password_limiter.check(f"email:{req_body.email.lower().strip()}")

    result = await db.execute(select(Profile).where(Profile.email == req_body.email))
    profile = result.scalars().first()

    if profile and uses_supabase_auth():
        send_supabase_password_reset(str(req_body.email))

    return ForgotPasswordResponse()

@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: Request,
    req_body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Reset user password using token received from recovery flow.
    Rate-limited by client IP.
    In production mode, tokens must be verified directly by Supabase.
    Locally signed tokens are rejected in production mode.
    """
    client_ip = get_client_ip(request)
    reset_password_limiter.check(f"ip:{client_ip}")

    user_id: Optional[str] = None

    if uses_supabase_auth():
        # Verify token with Supabase Auth
        supabase_user = verify_supabase_recovery_token(req_body.token)
        if supabase_user:
            user_id = supabase_user["user_id"]
        elif not settings.is_local_auth_allowed():
            # In production, local JWT fallback is strictly disabled
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token."
            )

    if not user_id:
        if not settings.is_local_auth_allowed():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token."
            )

        # Local test/dev fallback
        payload = decode_access_token(req_body.token)
        if not payload or not payload.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token."
            )
        user_id = payload["sub"]

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID in reset token."
        )

    result = await db.execute(select(Profile).where(Profile.id == user_uuid))
    profile = result.scalars().first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found."
        )

    if uses_supabase_auth():
        try:
            update_supabase_user_password(str(user_id), req_body.new_password)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password with auth provider."
            )

    _mock_password_store[profile.email] = hash_password(req_body.new_password)

    return ResetPasswordResponse()

