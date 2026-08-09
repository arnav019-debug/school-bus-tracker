import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_and_login(async_client: AsyncClient):
    # 1. Test Registration
    register_payload = {
        "email": "testparent@example.com",
        "password": "Password123!",
        "full_name": "Test Parent",
        "role": "admin",
        "phone": "+15551234567"
    }
    resp = await async_client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "testparent@example.com"
    assert data["user"]["role"] == "parent"
    token = data["access_token"]

    # 2. Test Login
    login_payload = {
        "email": "testparent@example.com",
        "password": "Password123!"
    }
    login_resp = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data

    # 3. Test Get Current User Profile (/auth/me)
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await async_client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "testparent@example.com"
    assert me_data["full_name"] == "Test Parent"

@pytest.mark.asyncio
async def test_unauthorized_access(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
