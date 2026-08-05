import jwt
from jwt import PyJWKClient
import bcrypt
import ssl
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from supabase import create_client, Client
from supabase_auth.errors import AuthApiError
from app.config import settings

logger = logging.getLogger("auth_service")

# Password Hashing Context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _init_supabase_client(api_key: Optional[str]) -> Optional[Client]:
    if not settings.SUPABASE_URL or not api_key:
        return None
    try:
        return create_client(settings.SUPABASE_URL, api_key)
    except Exception as e:
        logger.warning("Could not initialize Supabase client: %s", e)
        return None

# Public client (anon/publishable key) for sign-in and sign-up fallback
supabase: Optional[Client] = _init_supabase_client(settings.SUPABASE_KEY)
# Admin client (service role key) for server-side user creation
supabase_admin: Optional[Client] = _init_supabase_client(settings.SUPABASE_SERVICE_ROLE_KEY)

def uses_supabase_auth() -> bool:
    """True when the app is configured to authenticate against Supabase Auth."""
    return bool(settings.SUPABASE_URL and (settings.SUPABASE_KEY or settings.SUPABASE_SERVICE_ROLE_KEY))

def uses_supabase_database() -> bool:
    """True when connected to Supabase Postgres (profiles.id FK to auth.users)."""
    return settings.DATABASE_URL.startswith("postgresql")

def requires_supabase_auth() -> bool:
    """Supabase Auth is required when using Supabase Postgres."""
    return uses_supabase_auth() and uses_supabase_database()

def hash_password(password: str) -> str:
    """Hashes plain text password using bcrypt."""
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies plain text password against bcrypt hash."""
    pwd_bytes = plain_password.encode('utf-8')[:72]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Creates JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

_jwks_client: Optional[PyJWKClient] = None

def get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    if _jwks_client is None and settings.SUPABASE_URL:
        jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        ssl_context = ssl._create_unverified_context()
        _jwks_client = PyJWKClient(jwks_url, ssl_context=ssl_context)
    return _jwks_client

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodes JWT access token using SECRET_KEY, Supabase JWKS, or SUPABASE_JWT_SECRET."""
    # First attempt with local SECRET_KEY
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        pass

    # Second attempt with Supabase JWKS if SUPABASE_URL is provided
    jwks_client = get_jwks_client()
    if jwks_client:
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                options={"verify_aud": False},
                leeway=120
            )
            return payload
        except jwt.PyJWTError as e:
            logger.warning("Failed to decode JWT with Supabase JWKS: %s", e, exc_info=True)

    # Third attempt with Supabase JWT Secret if provided
    if settings.SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False}, leeway=120)
            return payload
        except jwt.PyJWTError as e:
            logger.debug("Failed to decode JWT with Supabase secret: %s", e)
    return None

def create_supabase_auth_user(
    email: str,
    password: str,
    *,
    full_name: str,
    role: str,
    phone: Optional[str] = None,
) -> str:
    """
    Create a user in Supabase Auth (auth.users) and return the auth user id.
    Prefers the admin API when a service role client is available.
    """
    user_metadata = {
        "full_name": full_name,
        "role": role,
        "phone": phone,
    }

    if supabase_admin and settings.SUPABASE_SERVICE_ROLE_KEY:
        try:
            auth_resp = supabase_admin.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": user_metadata,
            })
            if auth_resp and auth_resp.user and auth_resp.user.id:
                return auth_resp.user.id
            raise ValueError("Supabase admin create_user did not return a user id.")
        except AuthApiError:
            raise
        except Exception as e:
            raise ValueError(f"Supabase admin create_user failed: {e}") from e

    if supabase:
        try:
            auth_resp = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": user_metadata},
            })
            if auth_resp and auth_resp.user and auth_resp.user.id:
                return auth_resp.user.id
            raise ValueError("Supabase sign_up did not return a user id.")
        except AuthApiError:
            raise
        except Exception as e:
            raise ValueError(f"Supabase sign_up failed: {e}") from e

    raise RuntimeError("Supabase Auth is not configured.")

def authenticate_supabase_user(email: str, password: str):
    """
    Verify credentials against Supabase Auth (auth.users).
    Returns the auth response on success.
    """
    if not supabase:
        raise RuntimeError("Supabase Auth is not configured.")

    auth_resp = supabase.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })
    if not auth_resp or not auth_resp.session or not auth_resp.user:
        raise ValueError("Invalid credentials")
    return auth_resp

def create_local_auth_user_id() -> str:
    """Local-only auth user id for sqlite test environments without Supabase."""
    return str(uuid.uuid4())
