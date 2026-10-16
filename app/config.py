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
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Environment: local JWT auth fallback permitted ONLY in explicitly "development" or "test".
    # Unset or any other value defaults to production behavior.
    ENVIRONMENT: Optional[str] = None
    
    # Public Base URL and Password Reset Page
    PUBLIC_BASE_URL: Optional[str] = None
    PASSWORD_RESET_REDIRECT_URL: Optional[str] = None

    # CORS configuration (comma-separated list of allowed origins)
    CORS_ORIGINS: Optional[str] = None

    # Firebase Admin SDK credentials (JSON string or path to file)
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None

    def is_local_auth_allowed(self) -> bool:
        """Returns True ONLY when explicitly running in test or development mode."""
        if not self.ENVIRONMENT:
            return False
        return self.ENVIRONMENT.lower().strip() in ("test", "development")

    def validate_startup_configuration(self) -> None:
        """
        Validates critical configuration outside development/test mode.
        Startup fails with a clear error if SECRET_KEY is missing or shorter than 32 characters.
        """
        if not self.is_local_auth_allowed():
            if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                raise RuntimeError(
                    "FATAL STARTUP ERROR: SECRET_KEY environment variable is required and must be at least 32 characters long outside development/test mode."
                )

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
