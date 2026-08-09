import pytest


@pytest.mark.asyncio
async def test_create_gps_log_without_timestamp_uses_utc_now(async_client):
    register_payload = {
        "email": "drivergps@example.com",
        "password": "Password123!",
        "full_name": "Driver GPS User",
        "role": "driver",
        "phone": "+15550001111",
    }

    register_response = await async_client.post(
        "/api/v1/auth/register",
        json=register_payload,
    )
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]

    bus_response = await async_client.post(
        "/api/v1/buses",
        json={
            "bus_number": "GPS-101",
            "license_plate": "ABC-1234",
            "capacity": 42,
            "status": "active",
        },
        headers={
            "Authorization": f"Bearer {token}",
        },
    )
    assert bus_response.status_code == 201
    bus_id = bus_response.json()["id"]

    gps_response = await async_client.post(
        f"/api/v1/buses/{bus_id}/gps",
        json={
            "latitude": 40.7128,
            "longitude": -74.0060,
            "speed": 32.5,
            "heading": 90.0,
        },
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert gps_response.status_code == 200
    gps_data = gps_response.json()
    assert gps_data["bus_id"] == bus_id
    assert gps_data["latitude"] == 40.7128
    assert gps_data["longitude"] == -74.0060
    assert gps_data["speed"] == 32.5
    assert gps_data["heading"] == 90.0
    assert gps_data["timestamp"] is not None

    latest_response = await async_client.get(
        f"/api/v1/buses/{bus_id}/gps/latest",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert latest_response.status_code == 200
    latest_data = latest_response.json()
    assert latest_data["bus_id"] == bus_id
    assert latest_data["latitude"] == 40.7128
