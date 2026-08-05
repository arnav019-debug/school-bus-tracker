import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services import auth_service

# In-memory SQLite engine for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

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
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
