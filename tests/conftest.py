import os

# HARD RULE 3 & Amendment 6: Force SQLite in test environment BEFORE any app imports
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.main import app
from app.database import Base, get_db
from app.services import auth_service

# Ensure settings object in memory is also pointing to SQLite
settings.DATABASE_URL = TEST_DB_URL
settings.ENVIRONMENT = "test"
settings.SUPABASE_URL = None
settings.SUPABASE_KEY = None
settings.SUPABASE_SERVICE_ROLE_KEY = None

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession
)

@pytest.fixture(autouse=True, scope="session")
def guard_sqlite_only():
    """Fails loudly if any test or setting would connect to a non-SQLite URL."""
    engine_url_str = str(test_engine.url)
    settings_url_str = str(settings.DATABASE_URL)
    if "sqlite" not in engine_url_str:
        raise RuntimeError(f"FATAL: Test engine is configured with non-SQLite URL: {engine_url_str}")
    if "sqlite" not in settings_url_str:
        raise RuntimeError(f"FATAL: App settings DATABASE_URL is non-SQLite URL: {settings_url_str}")

@pytest.fixture(autouse=True)
def disable_supabase_auth(monkeypatch):
    """Tests use sqlite without auth.users FK; force local auth fallback."""
    monkeypatch.setattr(auth_service.settings, "DATABASE_URL", TEST_DB_URL)
    monkeypatch.setattr(auth_service.settings, "SUPABASE_URL", None)
    monkeypatch.setattr(auth_service.settings, "SUPABASE_KEY", None)
    monkeypatch.setattr(auth_service.settings, "SUPABASE_SERVICE_ROLE_KEY", None)
    monkeypatch.setattr(auth_service, "supabase", None)
    monkeypatch.setattr(auth_service, "supabase_admin", None)

@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        # Guard: check the engine actually used by this session
        bind_engine = session.bind
        if bind_engine is None or "sqlite" not in str(bind_engine.url):
            raise RuntimeError(f"FATAL: Database session bound to non-SQLite engine: {bind_engine}")
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
