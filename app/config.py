import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "School Bus Tracking API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Supabase & Database configurations
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    SUPABASE_JWT_SECRET: str = "super-secret-jwt-key-change-in-production-supabase-secret"
    
    # Async PostgreSQL connection string (defaults to SQLite memory for testing if empty or fallback)
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
    
    # JWT authentication settings
    SECRET_KEY: str = "your-custom-secret-key-for-local-jwt-tokens-if-supabase-is-offline"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Environment: production by default. Local JWT auth fallback only permitted in "test" or "development".
    ENVIRONMENT: str = "production"
    
    # Public Base URL and Password Reset Page
    PUBLIC_BASE_URL: Optional[str] = None
    PASSWORD_RESET_REDIRECT_URL: Optional[str] = None

    # CORS configuration (comma-separated list of allowed origins)
    CORS_ORIGINS: Optional[str] = None

    # Firebase Admin SDK credentials (JSON string or path to file)
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None

    def is_local_auth_allowed(self) -> bool:
        """Returns True only when explicitly running in test or development mode."""
        return self.ENVIRONMENT.lower().strip() in ("test", "development")

    def get_password_reset_redirect_url(self) -> str:
        """Determines the public URL for the password reset completion page."""
        if self.PASSWORD_RESET_REDIRECT_URL:
            return self.PASSWORD_RESET_REDIRECT_URL
        if self.PUBLIC_BASE_URL:
            return f"{self.PUBLIC_BASE_URL.rstrip('/')}/reset-password"
        return "/reset-password"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
