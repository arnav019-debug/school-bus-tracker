import pytest
from httpx import AsyncClient
from app.services.attendance_service import get_kolkata_today

async def get_user_auth(async_client: AsyncClient, email: str, role: str) -> tuple[dict, str]:
    register_payload = {
        "email": email,
        "password": "SecretPassword123!",
        "full_name": f"{role.capitalize()} User",
        "role": role,
    }
    resp = await async_client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    user_id = resp.json()["user"]["id"]
    return {"Authorization": f"Bearer {token}"}, user_id

@pytest.mark.asyncio
async def test_device_token_registration_and_unregistration(async_client: AsyncClient):
    # Unauthenticated fails
    resp = await async_client.post("/api/v1/notifications/register-token", json={"token": "tok-123"})
    assert resp.status_code == 401

    parent_headers, parent_id = await get_user_auth(async_client, "parent_notif@example.com", "parent")

    # Register token for parent
    resp = await async_client.post(
        "/api/v1/notifications/register-token",
        json={"token": "parent-fcm-token-1", "platform": "android"},
        headers=parent_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == "parent-fcm-token-1"
    assert data["platform"] == "android"
    assert data["user_id"] == parent_id

    # Re-registering same token with new platform updates it
    resp = await async_client.post(
        "/api/v1/notifications/register-token",
        json={"token": "parent-fcm-token-1", "platform": "ios"},
        headers=parent_headers
    )
    assert resp.status_code == 200
    assert resp.json()["platform"] == "ios"

    # Unregister token
    resp = await async_client.post(
        "/api/v1/notifications/unregister-token",
        json={"token": "parent-fcm-token-1"},
        headers=parent_headers
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_absent_notification_trigger_and_suppression(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_notif@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "parent_absent@example.com", "parent")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher_absent@example.com", "teacher")

    # 1. Parent registers device token
    resp = await async_client.post(
        "/api/v1/notifications/register-token",
        json={"token": "token-for-absent-test-xyz", "platform": "android"},
        headers=parent_headers
    )
    assert resp.status_code == 200

    # 2. Admin creates bus, route assigned to teacher, and student linked to parent
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-NOTIF-1",
        "license_plate": "DL-01-XX-9999",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    assert bus_resp.status_code == 201
    bus_id = bus_resp.json()["id"]

    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Notif Route",
        "start_location": "Start",
        "end_location": "End",
        "bus_id": bus_id,
        "teacher_id": teacher_id,
        "status": "active"
    }, headers=admin_headers)
    assert route_resp.status_code == 201
    route_id = route_resp.json()["id"]

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Rohan",
        "last_name": "Sharma",
        "grade": "Grade 3",
        "parent_id": parent_id,
        "route_id": route_id
    }, headers=admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    today = get_kolkata_today()

    # 3. Teacher marks student absent
    resp = await async_client.post(
        "/api/v1/attendance",
        json={
            "student_id": student_id,
            "status": "absent",
            "action_type": "pickup",
            "attendance_date": today.isoformat()
        },
        headers=teacher_headers
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "absent"

    # 4. Check parent's notification logs
    logs_resp = await async_client.get("/api/v1/notifications/logs", headers=parent_headers)
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    assert len(logs) == 1
    assert "Rohan" in logs[0]["title"]
    assert logs[0]["status"] == "sent"
    assert logs[0]["data_payload"]["student_id"] == student_id

    # 5. Duplicate suppression check:
    # Marking absent again on same date/action does not create another sent log
    resp = await async_client.post(
        "/api/v1/attendance",
        json={
            "student_id": student_id,
            "status": "absent",
            "action_type": "pickup",
            "attendance_date": today.isoformat()
        },
        headers=teacher_headers
    )
    assert resp.status_code == 200

    logs_resp2 = await async_client.get("/api/v1/notifications/logs", headers=parent_headers)
    assert logs_resp2.status_code == 200
    sent_logs = [l for l in logs_resp2.json() if l["status"] == "sent"]
    assert len(sent_logs) == 1


@pytest.mark.asyncio
async def test_notification_logs_data_scoping(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_scope@example.com", "admin")
    p1_headers, p1_id = await get_user_auth(async_client, "p1_logs@example.com", "parent")
    p2_headers, p2_id = await get_user_auth(async_client, "p2_logs@example.com", "parent")

    # Both parents register tokens
    await async_client.post(
        "/api/v1/notifications/register-token",
        json={"token": "p1-token", "platform": "android"},
        headers=p1_headers
    )
    await async_client.post(
        "/api/v1/notifications/register-token",
        json={"token": "p2-token", "platform": "android"},
        headers=p2_headers
    )

    # Admin lists logs with filter
    admin_p1_logs = await async_client.get(f"/api/v1/notifications/logs?user_id={p1_id}", headers=admin_headers)
    assert admin_p1_logs.status_code == 200

    # Non-admin sees only own logs (initially empty)
    p1_logs = await async_client.get("/api/v1/notifications/logs", headers=p1_headers)
    assert p1_logs.status_code == 200
    assert len(p1_logs.json()) == 0
