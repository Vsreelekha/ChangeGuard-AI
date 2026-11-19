from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """GET /health must return status healthy and project ChangeGuard AI."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["project"] == "ChangeGuard AI"


def test_root_endpoint(client: TestClient):
    """GET / must provide basic API metadata, docs URL, and version."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert data["version"] == "1.0.0"
    assert data["docs_url"] == "/docs"
    assert data["health_check"] == "/health"
