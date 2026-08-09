import pytest
from httpx import AsyncClient

async def get_auth_header(async_client: AsyncClient) -> dict:
    register_payload = {
        "email": "teacher@example.com",
        "password": "SecretPassword123!",
        "full_name": "Teacher Member",
        "role": "teacher"
    }
    resp = await async_client.post("/api/v1/auth/register", json=register_payload)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_buses_crud(async_client: AsyncClient):
    headers = await get_auth_header(async_client)

    # 1. Create Bus
    bus_payload = {
        "bus_number": "BUS-99",
        "license_plate": "XYZ-999",
        "capacity": 45,
        "status": "active"
    }
    create_resp = await async_client.post("/api/v1/buses/", json=bus_payload, headers=headers)
    assert create_resp.status_code == 201
    bus = create_resp.json()
    assert bus["bus_number"] == "BUS-99"
    bus_id = bus["id"]

    # 2. List Buses
    list_resp = await async_client.get("/api/v1/buses/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Get Bus by ID
    get_resp = await async_client.get(f"/api/v1/buses/{bus_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == bus_id

    # 4. Update Bus
    update_payload = {"status": "maintenance", "capacity": 50}
    update_resp = await async_client.put(f"/api/v1/buses/{bus_id}", json=update_payload, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "maintenance"
    assert update_resp.json()["capacity"] == 50

    # 5. Delete Bus
    del_resp = await async_client.delete(f"/api/v1/buses/{bus_id}", headers=headers)
    assert del_resp.status_code == 204

    # Verify Deletion
    get_after_del = await async_client.get(f"/api/v1/buses/{bus_id}", headers=headers)
    assert get_after_del.status_code == 404

@pytest.mark.asyncio
async def test_drivers_crud(async_client: AsyncClient):
    headers = await get_auth_header(async_client)

    # 1. Create Driver
    driver_payload = {
        "license_number": "DL-11223344",
        "phone": "+1555998877",
        "status": "active"
    }
    create_resp = await async_client.post("/api/v1/drivers/", json=driver_payload, headers=headers)
    assert create_resp.status_code == 201
    driver = create_resp.json()
    driver_id = driver["id"]

    # 2. List Drivers
    list_resp = await async_client.get("/api/v1/drivers/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Update Driver
    update_resp = await async_client.put(f"/api/v1/drivers/{driver_id}", json={"status": "on_duty"}, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "on_duty"

    # 4. Delete Driver
    del_resp = await async_client.delete(f"/api/v1/drivers/{driver_id}", headers=headers)
    assert del_resp.status_code == 204

@pytest.mark.asyncio
async def test_routes_crud(async_client: AsyncClient):
    headers = await get_auth_header(async_client)

    # 1. Create Route
    route_payload = {
        "name": "East Express Route",
        "start_location": "East Station",
        "end_location": "High School",
        "waypoints": [{"stop_name": "Park Ave", "lat": 37.7, "lng": -122.4}],
        "scheduled_start_time": "07:30:00",
        "scheduled_end_time": "08:15:00",
        "status": "planned"
    }
    create_resp = await async_client.post("/api/v1/routes/", json=route_payload, headers=headers)
    assert create_resp.status_code == 201
    route = create_resp.json()
    route_id = route["id"]
    assert route["name"] == "East Express Route"

    # 2. List Routes
    list_resp = await async_client.get("/api/v1/routes/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Update Route
    update_resp = await async_client.put(f"/api/v1/routes/{route_id}", json={"status": "in_progress"}, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "in_progress"

    # 4. Delete Route
    del_resp = await async_client.delete(f"/api/v1/routes/{route_id}", headers=headers)
    assert del_resp.status_code == 204

@pytest.mark.asyncio
async def test_students_crud(async_client: AsyncClient):
    headers = await get_auth_header(async_client)

    # 1. Create Student
    student_payload = {
        "first_name": "Johnny",
        "last_name": "Doe",
        "grade": "Grade 3",
        "pickup_stop": "Main St & 4th Ave",
        "dropoff_stop": "Primary School"
    }
    create_resp = await async_client.post("/api/v1/students/", json=student_payload, headers=headers)
    assert create_resp.status_code == 201
    student = create_resp.json()
    student_id = student["id"]
    assert student["first_name"] == "Johnny"
    assert "qr_code_id" in student

    # 2. List Students
    list_resp = await async_client.get("/api/v1/students/", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Update Student
    update_resp = await async_client.put(f"/api/v1/students/{student_id}", json={"grade": "Grade 4"}, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["grade"] == "Grade 4"

    # 4. Delete Student
    del_resp = await async_client.delete(f"/api/v1/students/{student_id}", headers=headers)
    assert del_resp.status_code == 204
