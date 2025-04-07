@pytest.mark.asyncio
async def test_get_latest_sensor_readings():
    async with AsyncClient(base_url="http://localhost:8000") as client:
        response = await client.get("/api/sensors/latest")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for sensor in data:
        assert "sensor_id" in sensor
        assert "sensor_name" in sensor
        assert "value" in sensor