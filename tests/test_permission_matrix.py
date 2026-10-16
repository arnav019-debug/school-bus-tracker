import pytest
from datetime import timedelta
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
async def test_comprehensive_role_permission_matrix(async_client: AsyncClient):
    # Setup test users for all 4 roles
    admin_headers, admin_id = await get_user_auth(async_client, "matrix_admin@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "matrix_teacher@example.com", "teacher")
    parent_headers, parent_id = await get_user_auth(async_client, "matrix_parent@example.com", "parent")
    driver_headers, driver_id = await get_user_auth(async_client, "matrix_driver@example.com", "driver")

    # 1. Unauthenticated gets 401 on protected endpoints
    unauth_endpoints = [
        "/api/v1/buses",
        "/api/v1/drivers",
        "/api/v1/routes",
        "/api/v1/students",
        "/api/v1/attendance",
        "/api/v1/notifications/logs",
        "/api/v1/route-change-requests",
    ]
    for ep in unauth_endpoints:
        resp = await async_client.get(ep)
        assert resp.status_code == 401, f"{ep} did not reject unauthenticated user with 401"

    # 2. Setup bus, route, and student
    bus_payload = {
        "bus_number": "BUS-MATRIX-1",
        "license_plate": "DL-01-MX-0001",
        "capacity": 40,
        "status": "active"
    }
    admin_bus_resp = await async_client.post("/api/v1/buses/", json=bus_payload, headers=admin_headers)
    assert admin_bus_resp.status_code == 201
    bus_id = admin_bus_resp.json()["id"]

    route_payload = {
        "name": "Matrix Route",
        "start_location": "School",
        "end_location": "Suburbs",
        "bus_id": bus_id,
        "teacher_id": teacher_id,
        "status": "active"
    }
    admin_route_resp = await async_client.post("/api/v1/routes/", json=route_payload, headers=admin_headers)
    assert admin_route_resp.status_code == 201
    route_id = admin_route_resp.json()["id"]

    student_payload = {
        "first_name": "MatrixKid",
        "last_name": "Test",
        "grade": "Grade 1",
        "parent_id": parent_id,
        "route_id": route_id
    }
    admin_student_resp = await async_client.post("/api/v1/students/", json=student_payload, headers=admin_headers)
    assert admin_student_resp.status_code == 201
    student_id = admin_student_resp.json()["id"]

    # 3. GPS Authorization matrix on /buses/{bus_id}/gps:
    # - Admin: allowed
    # - Teacher: 403
    # - Parent: 403
    gps_payload = {"latitude": 28.6139, "longitude": 77.2090, "speed": 25.0}
    resp_teacher_gps = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=teacher_headers)
    assert resp_teacher_gps.status_code == 403

    resp_parent_gps = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=parent_headers)
    assert resp_parent_gps.status_code == 403

    resp_admin_gps = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=admin_headers)
    assert resp_admin_gps.status_code == 200

    # 4. Attendance Marking & Deletion matrix:
    today = get_kolkata_today()
    # - Parent cannot mark attendance (403)
    resp = await async_client.post("/api/v1/attendance", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
        "attendance_date": today.isoformat()
    }, headers=parent_headers)
    assert resp.status_code == 403

    # - Driver cannot mark attendance (403)
    resp = await async_client.post("/api/v1/attendance", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
        "attendance_date": today.isoformat()
    }, headers=driver_headers)
    assert resp.status_code == 403

    # - Assigned teacher marks attendance (201)
    att_resp = await async_client.post("/api/v1/attendance", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
        "attendance_date": today.isoformat()
    }, headers=teacher_headers)
    assert att_resp.status_code == 201
    att_id = att_resp.json()["id"]

    # - Teacher cannot DELETE attendance (403 Admin only)
    resp = await async_client.delete(f"/api/v1/attendance/{att_id}", headers=teacher_headers)
    assert resp.status_code == 403

    # 5. Route Change Request permissions:
    # - Teacher & Driver cannot submit request (403)
    rc_payload = {
        "student_id": student_id,
        "target_route_id": route_id,
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=2)).isoformat(),
        "reason": "Temporary stay"
    }
    resp = await async_client.post("/api/v1/route-change-requests", json=rc_payload, headers=teacher_headers)
    assert resp.status_code == 403

    resp = await async_client.post("/api/v1/route-change-requests", json=rc_payload, headers=driver_headers)
    assert resp.status_code == 403

    # - Parent of student can submit (201)
    p_rc = await async_client.post("/api/v1/route-change-requests", json=rc_payload, headers=parent_headers)
    assert p_rc.status_code == 201
    rc_id = p_rc.json()["id"]

    # - Teacher and Parent cannot approve (403)
    resp = await async_client.put(f"/api/v1/route-change-requests/{rc_id}/approve", headers=teacher_headers)
    assert resp.status_code == 403

    resp = await async_client.put(f"/api/v1/route-change-requests/{rc_id}/approve", headers=parent_headers)
    assert resp.status_code == 403

    # - Admin approves (200)
    resp = await async_client.put(f"/api/v1/route-change-requests/{rc_id}/approve", headers=admin_headers)
    assert resp.status_code == 200

    # 6. Admin deletes attendance record (204)
    del_resp = await async_client.delete(f"/api/v1/attendance/{att_id}", headers=admin_headers)
    assert del_resp.status_code == 204
