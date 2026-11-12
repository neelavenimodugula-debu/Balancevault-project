from fastapi.testclient import TestClient

from ledgerline.main import app


def test_health_check_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_and_assets_are_served() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/app.js")

    assert page.status_code == 200
    assert "LedgerLine" in page.text
    assert script.status_code == 200
    assert "renderAccounts" in script.text


def test_swagger_and_openapi_documentation_served() -> None:
    with TestClient(app) as client:
        docs = client.get("/docs")
        redoc = client.get("/redoc")
        openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()
    assert redoc.status_code == 200
    assert openapi.status_code == 200

    schema = openapi.json()
    assert "components" in schema
    assert "securitySchemes" in schema["components"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert schema["info"]["title"] == "LedgerLine API"