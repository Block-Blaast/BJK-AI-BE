from bjk_server.main import create_app
from fastapi.testclient import TestClient


def test_health_lives_under_base_url():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/health" in paths
    assert "/health" not in paths


def test_old_root_health_is_gone():
    assert TestClient(create_app()).get("/health").status_code == 404
