import pytest
from httpx import AsyncClient

async def get_auth_token(async_client: AsyncClient, email: str, role: str) -> tuple[dict, str]:
    resp = await async_client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password123!",
        "full_name": f"{role.capitalize()} User",
        "role": role
    })
    assert resp.status_code == 201
    data = resp.json()
    token = data["access_token"]
    user_id = data["user"]["id"]
    return {"Authorization": f"Bearer {token}"}, user_id

@pytest.mark.asyncio
async def test_bus_gps_authorization(async_client: AsyncClient):
    admin_headers, admin_id = await get_auth_token(async_client, "admin_gps@example.com", "admin")
    driver1_headers, driver1_user_id = await get_auth_token(async_client, "driver1_gps@example.com", "driver")
    driver2_headers, driver2_user_id = await get_auth_token(async_client, "driver2_gps@example.com", "driver")
    parent_headers, parent_id = await get_auth_token(async_client, "parent_gps@example.com", "parent")

    # Create driver record for driver 1 linked to driver1_user_id
    driver_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "DL-GPS-111",
        "phone": "+1234567890",
        "status": "active",
        "user_id": driver1_user_id
    }, headers=admin_headers)
    assert driver_resp.status_code == 201
    driver1_id = driver_resp.json()["id"]

    # Create Bus assigned to driver1_id
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-GPS-01",
        "license_plate": "GPS-001",
        "capacity": 30,
        "status": "active",
        "driver_id": driver1_id
    }, headers=admin_headers)
    assert bus_resp.status_code == 201
    bus_id = bus_resp.json()["id"]

    # 1. Admin posting GPS -> 200 OK
    gps_payload = {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "speed": 25.0,
        "heading": 90.0
    }
    admin_gps_resp = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=admin_headers)
    assert admin_gps_resp.status_code == 200

    # 2. Assigned driver posting GPS -> 200 OK
    driver_gps_resp = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=driver1_headers)
    assert driver_gps_resp.status_code == 200
    assert driver_gps_resp.json()["bus_id"] == bus_id

    # 2. Parent posting GPS -> 403 Forbidden
    parent_gps_resp = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=parent_headers)
    assert parent_gps_resp.status_code == 403
    assert parent_gps_resp.json()["detail"] == "Not authorized to update this bus location"

    # 3. Unassigned driver posting GPS -> 403 Forbidden
    unassigned_gps_resp = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=driver2_headers)
    assert unassigned_gps_resp.status_code == 403
    assert unassigned_gps_resp.json()["detail"] == "Not authorized to update this bus location"

@pytest.mark.asyncio
async def test_driver_gps_authorized_via_route_assignment(async_client: AsyncClient):
    admin_headers, _ = await get_auth_token(async_client, "admin_route_gps@example.com", "admin")
    driver_headers, driver_user_id = await get_auth_token(async_client, "driver_route_gps@example.com", "driver")

    # Create driver
    driver_resp = await async_client.post("/api/v1/drivers/", json={
        "license_number": "DL-RT-GPS-1",
        "phone": "+1999888777",
        "status": "active",
        "user_id": driver_user_id
    }, headers=admin_headers)
    assert driver_resp.status_code == 201
    driver_id = driver_resp.json()["id"]

    # Create Bus with NO driver_id assigned directly to the bus
    bus_resp = await async_client.post("/api/v1/buses/", json={
        "bus_number": "BUS-ROUTE-ONLY",
        "license_plate": "RT-GPS-01",
        "capacity": 25,
        "status": "active",
    }, headers=admin_headers)
    assert bus_resp.status_code == 201
    bus_id = bus_resp.json()["id"]

    # Create Route linking the bus and assigning the driver (Admin UI pattern!)
    route_resp = await async_client.post("/api/v1/routes/", json={
        "name": "Route With Driver",
        "start_location": "Origin",
        "end_location": "School",
        "bus_id": bus_id,
        "driver_id": driver_id,
        "status": "active"
    }, headers=admin_headers)
    assert route_resp.status_code == 201

    # Driver posts GPS for this bus -> 200 OK because assigned via route!
    gps_payload = {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "speed": 35.0,
        "heading": 180.0
    }
    gps_resp = await async_client.post(f"/api/v1/buses/{bus_id}/gps", json=gps_payload, headers=driver_headers)
    assert gps_resp.status_code == 200
    assert gps_resp.json()["bus_id"] == bus_id

