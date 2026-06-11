import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.middleware.security_headers import SecurityHeadersMiddleware


def _make_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(SecurityHeadersMiddleware)

    @test_app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @test_app.get("/error")
    async def error():
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return test_app


@pytest.fixture
def client():
    test_app = _make_app()
    with TestClient(test_app) as c:
        yield c


def test_security_headers_on_normal_response(client):
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "max-age=31536000" in resp.headers["strict-transport-security"]
    assert "includeSubDomains" in resp.headers["strict-transport-security"]


def test_security_headers_on_error_response(client):
    resp = client.get("/error")
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "max-age=31536000" in resp.headers["strict-transport-security"]
