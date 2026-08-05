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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
