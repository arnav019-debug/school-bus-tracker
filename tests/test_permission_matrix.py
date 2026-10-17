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


@pytest.mark.asyncio
async def test_entity_crud_and_cross_scoping_permissions(async_client: AsyncClient):
    # Setup users
    admin_headers, admin_id = await get_user_auth(async_client, "crud_admin@example.com", "admin")
    t1_headers, t1_id = await get_user_auth(async_client, "crud_t1@example.com", "teacher")
    t2_headers, t2_id = await get_user_auth(async_client, "crud_t2@example.com", "teacher")
    p1_headers, p1_id = await get_user_auth(async_client, "crud_p1@example.com", "parent")
    p2_headers, p2_id = await get_user_auth(async_client, "crud_p2@example.com", "parent")
    d1_headers, d1_id = await get_user_auth(async_client, "crud_d1@example.com", "driver")
    d2_headers, d2_id = await get_user_auth(async_client, "crud_d2@example.com", "driver")

    # 1. Admin creates core infrastructure: Driver 1, Bus 1, Route 1, Student 1
    d1_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "LIC-CRUD-D1",
        "phone": "+1555111111",
        "user_id": d1_id,
        "status": "active"
    }, headers=admin_headers)
    assert d1_resp.status_code == 201
    driver_1_id = d1_resp.json()["id"]

    bus1_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-SCOPE-1",
        "license_plate": "LP-SCOPE-1",
        "capacity": 30,
        "driver_id": driver_1_id,
        "status": "active"
    }, headers=admin_headers)
    assert bus1_resp.status_code == 201
    bus_1_id = bus1_resp.json()["id"]

    route1_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route Scope 1",
        "start_location": "Depot",
        "end_location": "School",
        "bus_id": bus_1_id,
        "driver_id": driver_1_id,
        "teacher_id": t1_id,
        "status": "active"
    }, headers=admin_headers)
    assert route1_resp.status_code == 201
    route_1_id = route1_resp.json()["id"]

    student1_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "ChildOne",
        "last_name": "FamilyA",
        "grade": "Grade 2",
        "parent_id": p1_id,
        "route_id": route_1_id
    }, headers=admin_headers)
    assert student1_resp.status_code == 201
    student_1_id = student1_resp.json()["id"]

    # 2. Non-admin roles (Teacher, Driver, Parent) FORBIDDEN from POST/PUT/DELETE on core entities
    for role_name, h in [("Teacher", t1_headers), ("Driver", d1_headers), ("Parent", p1_headers)]:
        # Student mutations
        resp = await async_client.post("/api/v1/students/", json={"first_name": "X", "last_name": "Y"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to POST /students"
        resp = await async_client.put(f"/api/v1/students/{student_1_id}", json={"grade": "Grade 9"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to PUT /students"
        resp = await async_client.delete(f"/api/v1/students/{student_1_id}", headers=h)
        assert resp.status_code == 403, f"{role_name} was able to DELETE /students"

        # Route mutations
        resp = await async_client.post("/api/v1/routes/", json={"name": "Hacked Route", "start_location": "A", "end_location": "B"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to POST /routes"
        resp = await async_client.put(f"/api/v1/routes/{route_1_id}", json={"name": "Renamed"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to PUT /routes"
        resp = await async_client.delete(f"/api/v1/routes/{route_1_id}", headers=h)
        assert resp.status_code == 403, f"{role_name} was able to DELETE /routes"

        # Bus mutations
        resp = await async_client.post("/api/v1/buses/", json={"bus_number": f"B-BAD-{role_name}", "license_plate": f"L-BAD-{role_name}", "capacity": 20}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to POST /buses"
        resp = await async_client.put(f"/api/v1/buses/{bus_1_id}", json={"capacity": 99}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to PUT /buses"
        resp = await async_client.delete(f"/api/v1/buses/{bus_1_id}", headers=h)
        assert resp.status_code == 403, f"{role_name} was able to DELETE /buses"

        # Driver mutations
        resp = await async_client.post("/api/v1/drivers/", json={"license_number": f"D-BAD-{role_name}", "phone": "+1555999999"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to POST /drivers"
        resp = await async_client.put(f"/api/v1/drivers/{driver_1_id}", json={"phone": "+1555888888"}, headers=h)
        assert resp.status_code == 403, f"{role_name} was able to PUT /drivers"
        resp = await async_client.delete(f"/api/v1/drivers/{driver_1_id}", headers=h)
        assert resp.status_code == 403, f"{role_name} was able to DELETE /drivers"

    # 3. Read scoping: Parent 1 (assigned) vs Parent 2 (unassigned)
    # Parent 1 sees child 1, route 1, bus 1, driver 1
    p1_students = (await async_client.get("/api/v1/students/", headers=p1_headers)).json()
    assert any(s["id"] == student_1_id for s in p1_students)
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=p1_headers)).status_code == 200

    p1_routes = (await async_client.get("/api/v1/routes/", headers=p1_headers)).json()
    assert any(r["id"] == route_1_id for r in p1_routes)
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=p1_headers)).status_code == 200

    p1_buses = (await async_client.get("/api/v1/buses/", headers=p1_headers)).json()
    assert any(b["id"] == bus_1_id for b in p1_buses)
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=p1_headers)).status_code == 200

    p1_drivers = (await async_client.get("/api/v1/drivers/", headers=p1_headers)).json()
    assert any(d["id"] == driver_1_id for d in p1_drivers)
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=p1_headers)).status_code == 200

    # Parent 2 sees NOTHING of child 1, route 1, bus 1, driver 1
    p2_students = (await async_client.get("/api/v1/students/", headers=p2_headers)).json()
    assert not any(s["id"] == student_1_id for s in p2_students)
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=p2_headers)).status_code == 403

    p2_routes = (await async_client.get("/api/v1/routes/", headers=p2_headers)).json()
    assert not any(r["id"] == route_1_id for r in p2_routes)
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=p2_headers)).status_code == 403

    p2_buses = (await async_client.get("/api/v1/buses/", headers=p2_headers)).json()
    assert not any(b["id"] == bus_1_id for b in p2_buses)
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=p2_headers)).status_code == 403

    p2_drivers = (await async_client.get("/api/v1/drivers/", headers=p2_headers)).json()
    assert not any(d["id"] == driver_1_id for d in p2_drivers)
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=p2_headers)).status_code == 403

    # 4. Read scoping: Teacher 1 (assigned) vs Teacher 2 (unassigned)
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=t1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=t2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=t1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=t2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=t1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=t2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=t1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=t2_headers)).status_code == 403

    # 5. Read scoping: Driver 1 (assigned) vs Driver 2 (unassigned)
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=d1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/routes/{route_1_id}", headers=d2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=d1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/students/{student_1_id}", headers=d2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=d1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/buses/{bus_1_id}", headers=d2_headers)).status_code == 403
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=d1_headers)).status_code == 200
    assert (await async_client.get(f"/api/v1/drivers/{driver_1_id}", headers=d2_headers)).status_code == 403

