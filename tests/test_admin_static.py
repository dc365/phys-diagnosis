from fastapi.testclient import TestClient

from backend.app.main import app


def test_root_serves_management_dashboard():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "可视化管理后台" in response.text


def test_map_view_remains_available():
    response = TestClient(app).get("/map")

    assert response.status_code == 200
    assert "天气诊断 GIS 地图" in response.text


def test_favicon_does_not_emit_browser_404():
    response = TestClient(app).get("/favicon.ico")

    assert response.status_code == 204
