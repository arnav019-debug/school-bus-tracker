import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_and_login(async_client: AsyncClient):
    # 1. Test Registration
    register_payload = {
        "email": "testadmin@example.com",
        "password": "Password123!",
        "full_name": "Test Administrator",
        "role": "admin",
        "phone": "+15551234567"
    }
    resp = await async_client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "testadmin@example.com"
    assert data["user"]["role"] == "admin"
    token = data["access_token"]

    # 2. Test Login
    login_payload = {
        "email": "testadmin@example.com",
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
    assert me_data["email"] == "testadmin@example.com"
    assert me_data["full_name"] == "Test Administrator"

@pytest.mark.asyncio
async def test_unauthorized_access(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/auth/me")
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_forgot_password_generic_response(async_client: AsyncClient):
    from app.services.rate_limiter import forgot_password_limiter
    forgot_password_limiter.reset()

    # 1. Register a user
    register_payload = {
        "email": "forgot_user@example.com",
        "password": "Password123!",
        "full_name": "Forgot User",
        "role": "parent",
    }
    reg_resp = await async_client.post("/api/v1/auth/register", json=register_payload)
    assert reg_resp.status_code == 201

    # 2. Existing user -> Generic response
    res1 = await async_client.post("/api/v1/auth/forgot-password", json={"email": "forgot_user@example.com"})
    assert res1.status_code == 200
    expected_msg = "If an account with that email exists, a password reset link has been sent."
    assert res1.json()["message"] == expected_msg
    # Tokens must NEVER be returned in response
    assert "token" not in res1.json()

    # 3. Nonexistent user -> EXACT same generic response
    res2 = await async_client.post("/api/v1/auth/forgot-password", json={"email": "nobody_exists@example.com"})
    assert res2.status_code == 200
    assert res2.json()["message"] == expected_msg
    assert "token" not in res2.json()

@pytest.mark.asyncio
async def test_password_strength_validation(async_client: AsyncClient):
    from app.services.auth_service import create_access_token

    dummy_token = create_access_token({"sub": "some-id", "type": "recovery"})

    weak_passwords = [
        "short",             # too short (< 8)
        "nouppercase123!",   # no uppercase
        "NOLOWERCASE123!",   # no lowercase
        "NoDigitsHere!",     # no digit
        "NoSpecialChar123",  # no special char
    ]

    for weak_pwd in weak_passwords:
        resp = await async_client.post("/api/v1/auth/reset-password", json={
            "token": dummy_token,
            "new_password": weak_pwd,
        })
        assert resp.status_code == 422, f"Expected 422 for weak password: {weak_pwd}"

@pytest.mark.asyncio
async def test_reset_password_flow(async_client: AsyncClient):
    from app.services.rate_limiter import reset_password_limiter
    from app.services.auth_service import create_access_token
    reset_password_limiter.reset()

    # 1. Register user
    reg_resp = await async_client.post("/api/v1/auth/register", json={
        "email": "reset_flow@example.com",
        "password": "InitialPassword123!",
        "full_name": "Reset Flow User",
        "role": "parent",
    })
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["user"]["id"]

    # 2. Invalid token fails
    invalid_resp = await async_client.post("/api/v1/auth/reset-password", json={
        "token": "invalid.jwt.token",
        "new_password": "NewStrongPassword123!",
    })
    assert invalid_resp.status_code == 400

    # 3. Valid recovery token succeeds
    recovery_token = create_access_token({"sub": user_id, "type": "recovery"})
    reset_resp = await async_client.post("/api/v1/auth/reset-password", json={
        "token": recovery_token,
        "new_password": "NewStrongPassword123!",
    })
    assert reset_resp.status_code == 200
    assert "successfully reset" in reset_resp.json()["message"].lower()

    # 4. Old password no longer works
    old_login = await async_client.post("/api/v1/auth/login", json={
        "email": "reset_flow@example.com",
        "password": "InitialPassword123!",
    })
    assert old_login.status_code == 401

    # 5. New password works
    new_login = await async_client.post("/api/v1/auth/login", json={
        "email": "reset_flow@example.com",
        "password": "NewStrongPassword123!",
    })
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()

@pytest.mark.asyncio
async def test_auth_rate_limiting(async_client: AsyncClient):
    from app.services.rate_limiter import forgot_password_limiter
    forgot_password_limiter.reset()

    # 5 allowed requests
    for i in range(5):
        resp = await async_client.post("/api/v1/auth/forgot-password", json={"email": "ratelimit@example.com"})
        assert resp.status_code == 200

    # 6th request triggers 429 Too Many Requests
    resp6 = await async_client.post("/api/v1/auth/forgot-password", json={"email": "ratelimit@example.com"})
    assert resp6.status_code == 429
    assert "too many password reset requests" in resp6.json()["detail"].lower()

    # Clean up rate limiter for other tests
    forgot_password_limiter.reset()

@pytest.mark.asyncio
async def test_password_reset_page_serving_and_security_headers(async_client: AsyncClient):
    resp = await async_client.get("/reset-password")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Content-Security-Policy" in resp.headers
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
    assert "connect-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in resp.headers.get("cache-control", "")
    assert "Reset Password" in resp.text
    assert "School Bus Tracker" in resp.text

@pytest.mark.asyncio
async def test_locally_signed_token_rejected_in_production_mode(async_client: AsyncClient, monkeypatch):
    from app.config import settings
    from app.services.auth_service import create_access_token

    local_token = create_access_token({"sub": "test-uuid-prod", "type": "recovery"})

    # Switch to production mode without local fallback
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://xyzcompany.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "dummy-role-key-12345")

    resp = await async_client.post("/api/v1/auth/reset-password", json={
        "token": local_token,
        "new_password": "NewStrongPassword123!",
    })
    assert resp.status_code == 400
    assert "invalid or expired" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_rate_limiter_proxy_ip_and_per_email_bucket(async_client: AsyncClient):
    from app.services.rate_limiter import forgot_password_limiter
    forgot_password_limiter.reset()

    # Requests from different spoofed/proxy IPs with the SAME email should exhaust the per-email bucket (5 per hour)
    email = "proxy_test@example.com"
    for i in range(5):
        resp = await async_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email},
            headers={"X-Forwarded-For": f"198.51.100.{i + 1}, 10.0.0.1"}
        )
        assert resp.status_code == 200

    # 6th attempt from yet another IP fails because email limit is reached
    resp_blocked = await async_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": email},
        headers={"X-Forwarded-For": "198.51.100.99, 10.0.0.1"}
    )
    assert resp_blocked.status_code == 429
    forgot_password_limiter.reset()

@pytest.mark.asyncio
async def test_forged_token_rejected_when_environment_unset(async_client: AsyncClient, monkeypatch):
    import uuid
    import jwt
    from app.config import settings

    # Token signed with forged arbitrary secret
    forged_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "exp": 9999999999},
        "forged-local-secret-key-that-should-never-be-accepted-by-backend",
        algorithm="HS256"
    )

    # ENVIRONMENT is unset (None)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://xyzcompany.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "dummy-key")

    resp = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401
    assert "could not validate credentials" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_forged_token_rejected_when_environment_production(async_client: AsyncClient, monkeypatch):
    import uuid
    import jwt
    from app.config import settings

    forged_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "exp": 9999999999},
        "forged-local-secret-key-that-should-never-be-accepted-by-backend",
        algorithm="HS256"
    )

    # ENVIRONMENT is explicitly "production"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://xyzcompany.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "dummy-key")

    resp = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401
    assert "could not validate credentials" in resp.json()["detail"].lower()

def test_startup_fails_if_secret_key_missing_or_short_outside_dev_test(monkeypatch):
    from app.config import settings

    # Case 1: ENVIRONMENT is unset (None), SECRET_KEY is missing
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "SECRET_KEY", None)
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup_configuration()
    assert "SECRET_KEY environment variable is required and must be at least 32 characters" in str(exc_info.value)

    # Case 2: ENVIRONMENT is "production", SECRET_KEY is too short (< 32 chars)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "short-secret-key")
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup_configuration()
    assert "at least 32 characters" in str(exc_info.value)

    # Case 3: ENVIRONMENT is explicitly "test" or "development" -> passes even with no secret
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "SECRET_KEY", None)
    settings.validate_startup_configuration()  # Should not raise



