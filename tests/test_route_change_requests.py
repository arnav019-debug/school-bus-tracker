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
async def test_route_change_request_crud_and_permissions(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_rc@example.com", "admin")
    parent1_headers, parent1_id = await get_user_auth(async_client, "p1_rc@example.com", "parent")
    parent2_headers, _ = await get_user_auth(async_client, "p2_rc@example.com", "parent")
    teacher_headers, _ = await get_user_auth(async_client, "t_rc@example.com", "teacher")

    # 1. Setup routes
    route1_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route 1",
        "start_location": "S1",
        "end_location": "E1",
        "status": "active"
    }, headers=admin_headers)
    assert route1_resp.status_code == 201
    route1_id = route1_resp.json()["id"]

    route2_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route 2",
        "start_location": "S2",
        "end_location": "E2",
        "status": "active"
    }, headers=admin_headers)
    assert route2_resp.status_code == 201
    route2_id = route2_resp.json()["id"]

    # 2. Setup student for parent 1
    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Aarav",
        "last_name": "Patel",
        "grade": "Grade 4",
        "parent_id": parent1_id,
        "route_id": route1_id
    }, headers=admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    today = get_kolkata_today()
    start_date = today + timedelta(days=1)
    end_date = today + timedelta(days=5)

    # 3. Parent 2 cannot request for Parent 1's student (403)
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Visiting grandparents"
    }, headers=parent2_headers)
    assert resp.status_code == 403

    # Teacher cannot submit route change request (403)
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Teacher attempt"
    }, headers=teacher_headers)
    assert resp.status_code == 403

    # Date validations: past date rejected
    past_date = today - timedelta(days=2)
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": past_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Visiting relatives"
    }, headers=parent1_headers)
    assert resp.status_code == 400

    # Date validations: > 30 days rejected
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": start_date.isoformat(),
        "end_date": (start_date + timedelta(days=35)).isoformat(),
        "reason": "Extended stay"
    }, headers=parent1_headers)
    assert resp.status_code == 400

    # 4. Parent 1 submits valid request
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Temporary stay with aunt"
    }, headers=parent1_headers)
    assert resp.status_code == 201
    req_data = resp.json()
    assert req_data["status"] == "pending"
    assert req_data["requested_by"] == parent1_id
    req_id = req_data["id"]

    # Overlapping request rejected
    resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route2_id,
        "start_date": (start_date + timedelta(days=1)).isoformat(),
        "end_date": (end_date + timedelta(days=1)).isoformat(),
        "reason": "Another request"
    }, headers=parent1_headers)
    assert resp.status_code == 400

    # 5. Scoping: Parent 2 cannot see Parent 1's request
    resp = await async_client.get(f"/api/v1/route-change-requests/{req_id}", headers=parent2_headers)
    assert resp.status_code == 403

    p2_list = await async_client.get("/api/v1/route-change-requests", headers=parent2_headers)
    assert p2_list.status_code == 200
    assert len(p2_list.json()) == 0

    # 6. Admin can see and approve request
    resp = await async_client.put(f"/api/v1/route-change-requests/{req_id}/approve", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["reviewed_by"] is not None


@pytest.mark.asyncio
async def test_route_change_rejection_and_cancellation(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_rc2@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "p_rc2@example.com", "parent")

    # Setup route and student
    r_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route X",
        "start_location": "Start X",
        "end_location": "End X",
        "status": "active"
    }, headers=admin_headers)
    assert r_resp.status_code == 201, r_resp.text
    route_id = r_resp.json()["id"]

    s_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Kavya",
        "last_name": "Iyer",
        "parent_id": parent_id,
        "route_id": route_id
    }, headers=admin_headers)
    student_id = s_resp.json()["id"]

    today = get_kolkata_today()

    # 1. Request 1: Admin rejects
    resp1 = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route_id,
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=3)).isoformat(),
        "reason": "Testing rejection"
    }, headers=parent_headers)
    req1_id = resp1.json()["id"]

    rej_resp = await async_client.put(
        f"/api/v1/route-change-requests/{req1_id}/reject",
        json={"review_notes": "Bus is at maximum capacity"},
        headers=admin_headers
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "rejected"
    assert rej_resp.json()["review_notes"] == "Bus is at maximum capacity"

    # 2. Request 2: Parent cancels
    resp2 = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route_id,
        "start_date": (today + timedelta(days=4)).isoformat(),
        "end_date": (today + timedelta(days=6)).isoformat(),
        "reason": "Testing cancellation"
    }, headers=parent_headers)
    req2_id = resp2.json()["id"]

    cancel_resp = await async_client.put(
        f"/api/v1/route-change-requests/{req2_id}/cancel",
        headers=parent_headers
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_effective_roster_swapping_on_approved_change(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_swap@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "parent_swap@example.com", "parent")
    t1_headers, t1_id = await get_user_auth(async_client, "t1_swap@example.com", "teacher")
    t2_headers, t2_id = await get_user_auth(async_client, "t2_swap@example.com", "teacher")

    # Create buses & routes
    b1_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-T1",
        "license_plate": "DL-01-T1-1111",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    assert b1_resp.status_code == 201, b1_resp.text
    b1_id = b1_resp.json()["id"]
    r1_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route 1",
        "start_location": "S1",
        "end_location": "E1",
        "bus_id": b1_id,
        "teacher_id": t1_id,
        "status": "active"
    }, headers=admin_headers)
    assert r1_resp.status_code == 201, r1_resp.text
    r1_id = r1_resp.json()["id"]

    b2_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-T2",
        "license_plate": "DL-01-T2-2222",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    assert b2_resp.status_code == 201, b2_resp.text
    b2_id = b2_resp.json()["id"]
    r2_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route 2",
        "start_location": "S2",
        "end_location": "E2",
        "bus_id": b2_id,
        "teacher_id": t2_id,
        "status": "active"
    }, headers=admin_headers)
    assert r2_resp.status_code == 201, r2_resp.text
    r2_id = r2_resp.json()["id"]

    # Student permanently on Route 1
    s_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Meera",
        "last_name": "Nair",
        "parent_id": parent_id,
        "route_id": r1_id
    }, headers=admin_headers)
    student_id = s_resp.json()["id"]

    today = get_kolkata_today()

    # Before change: Meera appears on Teacher 1's roster, NOT Teacher 2's
    roster_t1_before = (await async_client.get(f"/api/v1/attendance/roster?date={today.isoformat()}", headers=t1_headers)).json()
    assert any(s["student_id"] == student_id for s in roster_t1_before)

    roster_t2_before = (await async_client.get(f"/api/v1/attendance/roster?date={today.isoformat()}", headers=t2_headers)).json()
    assert not any(s["student_id"] == student_id for s in roster_t2_before)

    # Parent requests temporary change to Route 2 covering today
    req_resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": r2_id,
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=2)).isoformat(),
        "reason": "Temporarily taking Route 2"
    }, headers=parent_headers)
    assert req_resp.status_code == 201
    req_id = req_resp.json()["id"]

    # Admin approves
    appr_resp = await async_client.put(f"/api/v1/route-change-requests/{req_id}/approve", headers=admin_headers)
    assert appr_resp.status_code == 200

    # After approval for today:
    # Teacher 1's roster NO LONGER has Meera today (she is transferred away!)
    roster_t1_after = (await async_client.get(f"/api/v1/attendance/roster?date={today.isoformat()}", headers=t1_headers)).json()
    assert not any(s["student_id"] == student_id for s in roster_t1_after)

    # Teacher 2's roster NOW HAS Meera today!
    roster_t2_after = (await async_client.get(f"/api/v1/attendance/roster?date={today.isoformat()}", headers=t2_headers)).json()
    assert any(s["student_id"] == student_id for s in roster_t2_after)

    # Teacher 2 can record attendance for Meera today
    att_resp = await async_client.post("/api/v1/attendance", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
        "attendance_date": today.isoformat()
    }, headers=t2_headers)
    assert att_resp.status_code == 201
    assert att_resp.json()["status"] == "present"

    # Teacher 1 cannot record attendance for Meera today (she is on Teacher 2's route)
    att_fail = await async_client.post("/api/v1/attendance", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
        "attendance_date": today.isoformat()
    }, headers=t1_headers)
    assert att_fail.status_code == 403

@pytest.mark.asyncio
async def test_effective_route_and_bus_boundary_dates(async_client: AsyncClient):
    from tests.conftest import TestingSessionLocal
    from app.services.attendance_service import get_effective_route_and_bus_for_student

    admin_headers, _ = await get_user_auth(async_client, "admin_boundary@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "parent_boundary@example.com", "parent")

    # Buses
    b1_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-PERM",
        "license_plate": "PERM-01",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    b1_id = b1_resp.json()["id"]

    b2_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-TEMP",
        "license_plate": "TEMP-01",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    b2_id = b2_resp.json()["id"]

    # Routes
    r1_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Permanent Route",
        "start_location": "S1",
        "end_location": "E1",
        "bus_id": b1_id,
        "status": "active"
    }, headers=admin_headers)
    r1_id = r1_resp.json()["id"]

    r2_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Temporary Route",
        "start_location": "S2",
        "end_location": "E2",
        "bus_id": b2_id,
        "status": "active"
    }, headers=admin_headers)
    r2_id = r2_resp.json()["id"]

    # Student with permanent route R1
    s_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Boundary",
        "last_name": "Student",
        "parent_id": parent_id,
        "route_id": r1_id
    }, headers=admin_headers)
    student_id = s_resp.json()["id"]

    today = get_kolkata_today()
    start_date = today + timedelta(days=2)
    end_date = today + timedelta(days=5)

    # Request route change to R2 from start_date to end_date
    req_resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": r2_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Boundary testing"
    }, headers=parent_headers)
    assert req_resp.status_code == 201
    req_id = req_resp.json()["id"]

    # Approve
    appr_resp = await async_client.put(f"/api/v1/route-change-requests/{req_id}/approve", headers=admin_headers)
    assert appr_resp.status_code == 200

    async with TestingSessionLocal() as session:
        # 1. Day before start: permanent route & bus
        day_before = start_date - timedelta(days=1)
        route_eff, bus_eff = await get_effective_route_and_bus_for_student(session, student_id, day_before)
        assert route_eff == r1_id
        assert bus_eff == b1_id

        # 2. First day (start_date): temporary route & bus
        route_eff, bus_eff = await get_effective_route_and_bus_for_student(session, student_id, start_date)
        assert route_eff == r2_id
        assert bus_eff == b2_id

        # 3. Intermediate day: temporary route & bus
        mid_day = start_date + timedelta(days=1)
        route_eff, bus_eff = await get_effective_route_and_bus_for_student(session, student_id, mid_day)
        assert route_eff == r2_id
        assert bus_eff == b2_id

        # 4. Last day (end_date): temporary route & bus
        route_eff, bus_eff = await get_effective_route_and_bus_for_student(session, student_id, end_date)
        assert route_eff == r2_id
        assert bus_eff == b2_id

        # 5. Day after expiry (end_date + 1 day): reverts to permanent route & bus!
        day_after = end_date + timedelta(days=1)
        route_eff, bus_eff = await get_effective_route_and_bus_for_student(session, student_id, day_after)
        assert route_eff == r1_id
        assert bus_eff == b1_id

@pytest.mark.asyncio
async def test_student_endpoints_expose_effective_fields_before_during_after_swap(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_eff_api@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "parent_eff_api@example.com", "parent")

    # Drivers
    d1_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "LIC-EFF-D1",
        "phone": "+1555000001",
        "status": "active"
    }, headers=admin_headers)
    d1_id = d1_resp.json()["id"]

    d2_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "LIC-EFF-D2",
        "phone": "+1555000002",
        "status": "active"
    }, headers=admin_headers)
    d2_id = d2_resp.json()["id"]

    # Buses
    b1_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-EFF-1",
        "license_plate": "LP-EFF-1",
        "capacity": 30,
        "driver_id": d1_id,
        "status": "active"
    }, headers=admin_headers)
    b1_id = b1_resp.json()["id"]

    b2_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-EFF-2",
        "license_plate": "LP-EFF-2",
        "capacity": 30,
        "driver_id": d2_id,
        "status": "active"
    }, headers=admin_headers)
    b2_id = b2_resp.json()["id"]

    # Routes
    r1_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route Eff 1",
        "start_location": "S1",
        "end_location": "E1",
        "bus_id": b1_id,
        "driver_id": d1_id,
        "status": "active"
    }, headers=admin_headers)
    r1_id = r1_resp.json()["id"]

    r2_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route Eff 2",
        "start_location": "S2",
        "end_location": "E2",
        "bus_id": b2_id,
        "driver_id": d2_id,
        "status": "active"
    }, headers=admin_headers)
    r2_id = r2_resp.json()["id"]

    # Student
    s_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Effective",
        "last_name": "Student",
        "parent_id": parent_id,
        "route_id": r1_id
    }, headers=admin_headers)
    student_id = s_resp.json()["id"]

    today = get_kolkata_today()
    start_date = today + timedelta(days=2)
    end_date = today + timedelta(days=4)

    req_resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": r2_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": "Effective API testing"
    }, headers=parent_headers)
    assert req_resp.status_code == 201
    req_id = req_resp.json()["id"]

    appr_resp = await async_client.put(f"/api/v1/route-change-requests/{req_id}/approve", headers=admin_headers)
    assert appr_resp.status_code == 200

    # 1. Before swap date: permanent Route 1, Bus 1, Driver 1
    day_before = (start_date - timedelta(days=1)).isoformat()
    s_get_before = await async_client.get(f"/api/v1/students/{student_id}?date={day_before}", headers=parent_headers)
    assert s_get_before.status_code == 200
    data_before = s_get_before.json()
    assert data_before["route_id"] == r1_id
    assert data_before["effective_route_id"] == r1_id
    assert data_before["effective_bus_id"] == b1_id
    assert data_before["effective_driver"]["id"] == d1_id
    assert data_before["effective_driver"]["phone"] == "+1555000001"
    assert data_before["effective_driver_contact"]["phone"] == "+1555000001"

    s_list_before = await async_client.get(f"/api/v1/students?date={day_before}", headers=parent_headers)
    assert s_list_before.status_code == 200
    list_item_before = next(item for item in s_list_before.json() if item["id"] == student_id)
    assert list_item_before["effective_route_id"] == r1_id
    assert list_item_before["effective_bus_id"] == b1_id
    assert list_item_before["effective_driver"]["id"] == d1_id

    # 2. During swap date: temporary Route 2, Bus 2, Driver 2
    during_day = start_date.isoformat()
    s_get_during = await async_client.get(f"/api/v1/students/{student_id}?date={during_day}", headers=parent_headers)
    assert s_get_during.status_code == 200
    data_during = s_get_during.json()
    assert data_during["route_id"] == r1_id  # permanent remains Route 1
    assert data_during["effective_route_id"] == r2_id
    assert data_during["effective_bus_id"] == b2_id
    assert data_during["effective_driver"]["id"] == d2_id
    assert data_during["effective_driver"]["phone"] == "+1555000002"

    s_list_during = await async_client.get(f"/api/v1/students?date={during_day}", headers=parent_headers)
    assert s_list_during.status_code == 200
    list_item_during = next(item for item in s_list_during.json() if item["id"] == student_id)
    assert list_item_during["effective_route_id"] == r2_id
    assert list_item_during["effective_bus_id"] == b2_id
    assert list_item_during["effective_driver"]["id"] == d2_id

    # 3. After swap date: reverted to Route 1, Bus 1, Driver 1
    day_after = (end_date + timedelta(days=1)).isoformat()
    s_get_after = await async_client.get(f"/api/v1/students/{student_id}?date={day_after}", headers=parent_headers)
    assert s_get_after.status_code == 200
    data_after = s_get_after.json()
    assert data_after["route_id"] == r1_id
    assert data_after["effective_route_id"] == r1_id
    assert data_after["effective_bus_id"] == b1_id
    assert data_after["effective_driver"]["id"] == d1_id
    assert data_after["effective_driver"]["phone"] == "+1555000001"

    s_list_after = await async_client.get(f"/api/v1/students?date={day_after}", headers=parent_headers)
    assert s_list_after.status_code == 200
    list_item_after = next(item for item in s_list_after.json() if item["id"] == student_id)
    assert list_item_after["effective_route_id"] == r1_id
    assert list_item_after["effective_bus_id"] == b1_id
    assert list_item_after["effective_driver"]["id"] == d1_id


@pytest.mark.asyncio
async def test_admin_delete_route_change_request(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_del_rc@example.com", "admin")
    parent_headers, parent_id = await get_user_auth(async_client, "p_del_rc@example.com", "parent")

    # Setup student and request
    r_resp = await async_client.post("/api/v1/routes", json={
        "name": "Route for Deletion Test",
        "start_location": "A",
        "end_location": "B"
    }, headers=admin_headers)
    route_id = r_resp.json()["id"]

    s_resp = await async_client.post("/api/v1/students", json={
        "first_name": "Delete",
        "last_name": "TestStudent",
        "route_id": route_id,
        "parent_id": parent_id
    }, headers=admin_headers)
    student_id = s_resp.json()["id"]

    today = get_kolkata_today()
    req_resp = await async_client.post("/api/v1/route-change-requests", json={
        "student_id": student_id,
        "target_route_id": route_id,
        "start_date": today.isoformat(),
        "end_date": today.isoformat(),
        "reason": "Temporary change"
    }, headers=parent_headers)
    assert req_resp.status_code == 201
    req_id = req_resp.json()["id"]

    # Parent attempt to DELETE -> 403 Forbidden
    del_parent = await async_client.delete(f"/api/v1/route-change-requests/{req_id}", headers=parent_headers)
    assert del_parent.status_code == 403

    # Admin DELETE -> 204 No Content
    del_admin = await async_client.delete(f"/api/v1/route-change-requests/{req_id}", headers=admin_headers)
    assert del_admin.status_code == 204

    # Second DELETE -> 404 Not Found
    del_again = await async_client.delete(f"/api/v1/route-change-requests/{req_id}", headers=admin_headers)
    assert del_again.status_code == 404




