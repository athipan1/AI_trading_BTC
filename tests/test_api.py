from fastapi.testclient import TestClient

from app.api.main import app


def test_health_is_paper_only() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "paper"
