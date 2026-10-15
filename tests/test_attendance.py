import pytest
import uuid
from httpx import AsyncClient

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
async def test_attendance_roster_and_marking_by_assigned_teacher(async_client: AsyncClient):
    # Setup admin, teacher
    admin_headers, _ = await get_user_auth(async_client, "admin1@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher1@example.com", "teacher")

    # 1. Admin creates a bus
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-101",
        "license_plate": "DL-01-AB-1234",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    assert bus_resp.status_code == 201
    bus_id = bus_resp.json()["id"]

    # 2. Admin creates a route assigned to this teacher
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "North Route",
        "start_location": "Point A",
        "end_location": "School",
        "bus_id": bus_id,
        "teacher_id": teacher_id,
        "status": "planned"
    }, headers=admin_headers)
    assert route_resp.status_code == 201
    route_id = route_resp.json()["id"]

    # 3. Admin creates student on this route
    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Alice",
        "last_name": "Smith",
        "grade": "Grade 2",
        "route_id": route_id,
    }, headers=admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    # 4. Teacher checks roster
    roster_resp = await async_client.get(f"/api/v1/attendance/roster?route_id={route_id}", headers=teacher_headers)
    assert roster_resp.status_code == 200
    roster = roster_resp.json()
    assert len(roster) == 1
    assert roster[0]["student_id"] == student_id
    assert roster[0]["status"] is None

    # 5. Teacher marks attendance as 'present'
    mark_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "bus_id": bus_id,
        "route_id": route_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert mark_resp.status_code == 201
    att_data = mark_resp.json()
    assert att_data["student_id"] == student_id
    assert att_data["status"] == "present"
    assert att_data["action_type"] == "pickup"
    assert att_data["scanned_by"] == teacher_id
    assert att_data["attendance_date"] is not None

    # 6. Teacher checks roster again - student should show 'present'
    roster_resp2 = await async_client.get(f"/api/v1/attendance/roster?route_id={route_id}", headers=teacher_headers)
    assert roster_resp2.status_code == 200
    roster2 = roster_resp2.json()
    assert len(roster2) == 1
    assert roster2[0]["status"] == "present"

@pytest.mark.asyncio
async def test_attendance_unassigned_teacher_forbidden(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin2@example.com", "admin")
    teacher1_headers, teacher1_id = await get_user_auth(async_client, "teacher_a@example.com", "teacher")
    teacher2_headers, _ = await get_user_auth(async_client, "teacher_b@example.com", "teacher")

    # Route assigned to Teacher 1
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "East Route",
        "start_location": "Point E",
        "end_location": "School",
        "teacher_id": teacher1_id,
        "status": "planned"
    }, headers=admin_headers)
    route_id = route_resp.json()["id"]

    # Student on Teacher 1's route
    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Bob",
        "last_name": "Jones",
        "grade": "Grade 1",
        "route_id": route_id,
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    # Teacher 2 (not assigned) attempts to mark attendance -> 403 Forbidden
    mark_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher2_headers)
    assert mark_resp.status_code == 403
    detail = mark_resp.json()["detail"].lower()
    assert "not authorized" in detail or "not on your assigned route" in detail or "not assigned" in detail

@pytest.mark.asyncio
async def test_attendance_idempotent_upsert(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin3@example.com", "admin")

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Charlie",
        "last_name": "Brown",
        "grade": "Grade 3",
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    # 1. Mark present
    resp1 = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=admin_headers)
    assert resp1.status_code == 201
    att_id_1 = resp1.json()["id"]
    assert resp1.json()["status"] == "present"

    # 2. Mark absent for same student, date, and action_type (idempotent upsert)
    resp2 = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "absent",
        "action_type": "pickup",
    }, headers=admin_headers)
    assert resp2.status_code == 200
    att_id_2 = resp2.json()["id"]
    assert att_id_2 == att_id_1
    assert resp2.json()["status"] == "absent"

    # Verify only 1 record exists in total for this student
    list_resp = await async_client.get(f"/api/v1/attendance/?student_id={student_id}", headers=admin_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

@pytest.mark.asyncio
async def test_attendance_legacy_status_normalization(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin4@example.com", "admin")

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Daisy",
        "last_name": "Miller",
        "grade": "Grade 4",
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    # Legacy status 'boarded' should normalize to 'present'
    resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "boarded",
        "action_type": "pickup",
    }, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "present"

    # Legacy status 'dropped' should normalize to 'present'
    resp_drop = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "dropped",
        "action_type": "dropoff",
    }, headers=admin_headers)
    assert resp_drop.status_code == 201
    assert resp_drop.json()["status"] == "present"

@pytest.mark.asyncio
async def test_attendance_role_permissions_matrix(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin5@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher_perm@example.com", "teacher")
    parent_headers, _ = await get_user_auth(async_client, "parent_perm@example.com", "parent")
    driver_headers, _ = await get_user_auth(async_client, "driver_perm@example.com", "driver")

    # Route & student
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Perm Route",
        "start_location": "A",
        "end_location": "B",
        "teacher_id": teacher_id,
    }, headers=admin_headers)
    route_id = route_resp.json()["id"]

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Ethan",
        "last_name": "Hunt",
        "grade": "Grade 5",
        "route_id": route_id,
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    # 1. Unauthenticated gets 401
    unauth_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    })
    assert unauth_resp.status_code == 401

    # 2. Parent gets 403
    parent_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=parent_headers)
    assert parent_resp.status_code == 403

    # 3. Driver gets 403
    driver_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=driver_headers)
    assert driver_resp.status_code == 403

    # 4. Assigned Teacher succeeds
    teacher_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert teacher_resp.status_code == 201
    att_id = teacher_resp.json()["id"]

    # 5. Teacher cannot DELETE attendance (admin only) -> 403
    teach_del = await async_client.delete(f"/api/v1/attendance/{att_id}", headers=teacher_headers)
    assert teach_del.status_code == 403

    # 6. Admin can DELETE attendance -> 204
    admin_del = await async_client.delete(f"/api/v1/attendance/{att_id}", headers=admin_headers)
    assert admin_del.status_code == 204

@pytest.mark.asyncio
async def test_attendance_scoping_and_cross_family_leak_prevention(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin6@example.com", "admin")
    parent1_headers, parent1_id = await get_user_auth(async_client, "parent_one@example.com", "parent")
    parent2_headers, parent2_id = await get_user_auth(async_client, "parent_two@example.com", "parent")

    # Child 1 belongs to Parent 1
    child1_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Kid",
        "last_name": "One",
        "parent_id": parent1_id,
    }, headers=admin_headers)
    child1_id = child1_resp.json()["id"]

    # Child 2 belongs to Parent 2
    child2_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Kid",
        "last_name": "Two",
        "parent_id": parent2_id,
    }, headers=admin_headers)
    child2_id = child2_resp.json()["id"]

    # Mark attendance for both children
    att1_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": child1_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=admin_headers)
    att1_id = att1_resp.json()["id"]

    att2_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": child2_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=admin_headers)
    att2_id = att2_resp.json()["id"]

    # Parent 1 lists attendance -> must ONLY see child 1's record
    p1_list = await async_client.get("/api/v1/attendance/", headers=parent1_headers)
    assert p1_list.status_code == 200
    p1_records = p1_list.json()
    assert all(r["student_id"] == child1_id for r in p1_records)
    assert any(r["id"] == att1_id for r in p1_records)
    assert not any(r["id"] == att2_id for r in p1_records)

    # Parent 1 tries to access Child 2's attendance by ID -> 403 Forbidden
    p1_cross = await async_client.get(f"/api/v1/attendance/{att2_id}", headers=parent1_headers)
    assert p1_cross.status_code == 403

@pytest.mark.asyncio
async def test_attendance_put_status_only(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin7@example.com", "admin")

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Fiona",
        "last_name": "Gallagher",
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    create_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=admin_headers)
    att_id = create_resp.json()["id"]

    # Update status to 'absent'
    update_resp = await async_client.put(f"/api/v1/attendance/{att_id}", json={
        "status": "absent"
    }, headers=admin_headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "absent"
    assert update_resp.json()["student_id"] == student_id

@pytest.mark.asyncio
async def test_attendance_not_found(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin8@example.com", "admin")

    fake_student_id = str(uuid.uuid4())
    create_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": fake_student_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=admin_headers)
    assert create_resp.status_code == 404

    fake_att_id = str(uuid.uuid4())
    get_resp = await async_client.get(f"/api/v1/attendance/{fake_att_id}", headers=admin_headers)
    assert get_resp.status_code == 404

@pytest.mark.asyncio
async def test_attendance_date_validation_and_limits(async_client: AsyncClient):
    from datetime import date, timedelta
    from app.services.attendance_service import get_kolkata_today

    admin_headers, _ = await get_user_auth(async_client, "admin_dates@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher_dates@example.com", "teacher")

    today = get_kolkata_today()

    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Date Test Route",
        "start_location": "School",
        "end_location": "Gate",
        "teacher_id": teacher_id,
    }, headers=admin_headers)
    route_id = route_resp.json()["id"]

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Date",
        "last_name": "Tester",
        "route_id": route_id,
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    # 1. Past date within 7 days -> Teacher allowed
    past_3_days = today - timedelta(days=3)
    resp_past = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "attendance_date": past_3_days.isoformat(),
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert resp_past.status_code == 201
    assert resp_past.json()["attendance_date"] == past_3_days.isoformat()

    # 2. Future date -> Rejected with 400
    future_date = today + timedelta(days=1)
    resp_future = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "attendance_date": future_date.isoformat(),
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert resp_future.status_code == 400
    assert "future" in resp_future.json()["detail"].lower()

    # 3. Teacher beyond 7 days -> Rejected with 403
    old_date = today - timedelta(days=10)
    resp_old_teacher = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "attendance_date": old_date.isoformat(),
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert resp_old_teacher.status_code == 403
    assert "7 days" in resp_old_teacher.json()["detail"].lower()

    # 4. Admin beyond 7 days -> Allowed (unrestricted)
    resp_old_admin = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "attendance_date": old_date.isoformat(),
        "status": "absent",
        "action_type": "pickup",
    }, headers=admin_headers)
    assert resp_old_admin.status_code == 201
    assert resp_old_admin.json()["attendance_date"] == old_date.isoformat()

@pytest.mark.asyncio
async def test_admin_ui_assignment_flow_and_roster_link(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_ui_flow@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher_ui_flow@example.com", "teacher")

    # 1. Admin creates bus (AddBusScreen payload)
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-999",
        "license_plate": "MH-02-XY-9999",
        "capacity": 45,
        "status": "active"
    }, headers=admin_headers)
    assert bus_resp.status_code == 201
    bus_id = bus_resp.json()["id"]

    # 2. Admin creates driver
    driver_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "DL999999",
        "phone": "+919876543210",
        "status": "active"
    }, headers=admin_headers)
    assert driver_resp.status_code == 201
    driver_id = driver_resp.json()["id"]

    # 3. Admin creates route
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Metro Expressway Route",
        "start_location": "Metro Station",
        "end_location": "Main Campus",
        "status": "planned"
    }, headers=admin_headers)
    assert route_resp.status_code == 201
    route_id = route_resp.json()["id"]

    # 4. Admin assigns bus, driver, and teacher using RouteEditScreen contract:
    # {"bus_id": ..., "teacher_id": ..., "driver_id": ...}
    route_update_resp = await async_client.put(f"/api/v1/routes/{route_id}", json={
        "bus_id": bus_id,
        "teacher_id": teacher_id,
        "driver_id": driver_id,
    }, headers=admin_headers)
    assert route_update_resp.status_code == 200
    assert route_update_resp.json()["teacher_id"] == teacher_id
    assert route_update_resp.json()["bus_id"] == bus_id

    # 5. Admin creates and assigns student using StudentEditScreen contract:
    # {"first_name": ..., "last_name": ..., "grade": ..., "route_id": route_id, ...}
    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Oliver",
        "last_name": "Twist",
        "grade": "Grade 5",
        "route_id": route_id,
        "pickup_stop": "Metro Gate 2",
        "dropoff_stop": "Campus Drop Area",
    }, headers=admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    # 6. Teacher loads roster for this route
    roster_resp = await async_client.get(f"/api/v1/attendance/roster?route_id={route_id}", headers=teacher_headers)
    assert roster_resp.status_code == 200
    roster = roster_resp.json()
    assert len(roster) >= 1

    # Verify student is present in teacher roster with linked route and bus metadata
    matching = [s for s in roster if s["student_id"] == student_id]
    assert len(matching) == 1
    item = matching[0]
    assert item["first_name"] == "Oliver"
    assert item["last_name"] == "Twist"
    assert item["route_id"] == route_id
    assert item["route_name"] == "Metro Expressway Route"
    assert item["bus_id"] == bus_id
    assert item["bus_number"] == "BUS-999"
    assert item["status"] is None

    # 7. Teacher marks attendance for Oliver Twist
    mark_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "bus_id": bus_id,
        "route_id": route_id,
        "status": "present",
        "action_type": "pickup",
    }, headers=teacher_headers)
    assert mark_resp.status_code == 201
    assert mark_resp.json()["status"] == "present"

    # 8. Re-check roster: status should be updated to present
    roster_resp_after = await async_client.get(f"/api/v1/attendance/roster?route_id={route_id}", headers=teacher_headers)
    matching_after = [s for s in roster_resp_after.json() if s["student_id"] == student_id]
    assert matching_after[0]["status"] == "present"

@pytest.mark.asyncio
async def test_teacher_put_7_day_limit_and_admin_unrestricted(async_client: AsyncClient):
    from datetime import timedelta
    from app.services.attendance_service import get_kolkata_today

    admin_headers, _ = await get_user_auth(async_client, "admin_limit@example.com", "admin")
    teacher_headers, teacher_id = await get_user_auth(async_client, "teacher_limit@example.com", "teacher")

    # Create bus, route, and student
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-7DAY",
        "license_plate": "7DAY-01",
        "capacity": 30,
        "status": "active"
    }, headers=admin_headers)
    bus_id = bus_resp.json()["id"]

    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Limit Route",
        "start_location": "A",
        "end_location": "B",
        "bus_id": bus_id,
        "teacher_id": teacher_id,
        "status": "planned"
    }, headers=admin_headers)
    route_id = route_resp.json()["id"]

    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Tim",
        "last_name": "Old",
        "grade": "Grade 1",
        "route_id": route_id,
    }, headers=admin_headers)
    student_id = student_resp.json()["id"]

    today = get_kolkata_today()
    past_8_days = today - timedelta(days=8)

    # Admin creates attendance record for 8 days ago
    mark_resp = await async_client.post("/api/v1/attendance/", json={
        "student_id": student_id,
        "bus_id": bus_id,
        "route_id": route_id,
        "status": "absent",
        "action_type": "pickup",
        "attendance_date": past_8_days.isoformat(),
    }, headers=admin_headers)
    assert mark_resp.status_code == 201
    attendance_id = mark_resp.json()["id"]

    # Teacher attempts to edit record > 7 days old -> 403 Forbidden
    teacher_edit_resp = await async_client.put(f"/api/v1/attendance/{attendance_id}", json={
        "status": "present",
    }, headers=teacher_headers)
    assert teacher_edit_resp.status_code == 403
    assert "last 7 days" in teacher_edit_resp.json()["detail"].lower()

    # Admin edits the same old record -> 200 OK
    admin_edit_resp = await async_client.put(f"/api/v1/attendance/{attendance_id}", json={
        "status": "present",
    }, headers=admin_headers)
    assert admin_edit_resp.status_code == 200
    assert admin_edit_resp.json()["status"] == "present"

@pytest.mark.asyncio
async def test_driver_roster_access(async_client: AsyncClient):
    admin_headers, _ = await get_user_auth(async_client, "admin_drv_rost@example.com", "admin")
    driver_headers, driver_user_id = await get_user_auth(async_client, "driver_rost@example.com", "driver")

    # Create driver record
    driver_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "DL-ROST-01",
        "phone": "+9876543210",
        "status": "active",
        "user_id": driver_user_id,
    }, headers=admin_headers)
    assert driver_resp.status_code == 201
    driver_id = driver_resp.json()["id"]

    # Create route assigned to this driver
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Driver Route Roster",
        "start_location": "Depot",
        "end_location": "Campus",
        "driver_id": driver_id,
        "status": "planned"
    }, headers=admin_headers)
    assert route_resp.status_code == 201
    route_id = route_resp.json()["id"]

    # Create student on route
    student_resp = await async_client.post("/api/v1/students/", json={
        "first_name": "Rider",
        "last_name": "Student",
        "grade": "Grade 3",
        "route_id": route_id,
    }, headers=admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    # Driver fetches roster
    roster_resp = await async_client.get(f"/api/v1/attendance/roster?route_id={route_id}", headers=driver_headers)
    assert roster_resp.status_code == 200
    roster = roster_resp.json()
    assert len(roster) >= 1
    assert any(s["student_id"] == student_id for s in roster)


