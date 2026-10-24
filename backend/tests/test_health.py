from fastapi.testclient import TestClient

from app.core import database
from app.main import app

client = TestClient(app)  # not used as a context manager: lifespan (and the pool) is skipped


def test_health_ok(monkeypatch):
    monkeypatch.setattr(database, "ping", lambda: True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "app": "Synapsed", "database": True}


def test_health_degraded_when_database_is_down(monkeypatch):
    def broken():
        raise RuntimeError("no pool")

    monkeypatch.setattr(database, "ping", broken)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_cors_allows_local_frontend():
    response = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_frontend_origin_may_list_several_addresses():
    from app.core.config import Settings

    settings = Settings(frontend_origin=" https://a.example/ , https://b.example,,https://a.example ")
    assert settings.cors_origins == ["http://localhost:5173", "https://a.example", "https://b.example"]
    assert Settings(frontend_origin="").cors_origins == ["http://localhost:5173"]


def test_cors_rejects_other_origins():
    response = client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers
