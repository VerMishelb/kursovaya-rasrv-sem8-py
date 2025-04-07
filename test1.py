@pytest.mark.asyncio
async def test_websocket_dashboard (monkeypatch):
    # Заглушка
    async def mock_generate_dashboard_data(db):
        return {
            "sensor_readings": [],
            "recent_alerts": [],
            "production_status": {
                "status": "normal",
                "message": "Test message",
                "metrics": {}
            }
        }

monkeypatch.setattr(target: "web.app.generate_dashboard_data", mock_generate_dashboard_data)

# WebSocket
client = TestClient (app)
with client.websocket_connect("/ws/dashboard") as websocket:
    data = websocket.receive_json()
    assert "production_status" in data
    assert data["production_status"]["status"] == "normal"