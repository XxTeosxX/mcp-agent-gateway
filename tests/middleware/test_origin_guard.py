import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.origin_guard import OriginGuardMiddleware


def _make_app(allowed_origins: list[str]) -> FastAPI:
    test_app = FastAPI()

    @test_app.get("/mcp/")
    async def mcp():
        return {"transport": "streamable-http"}

    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    test_app.add_middleware(OriginGuardMiddleware, allowed_origins=allowed_origins)
    return test_app


@pytest.fixture
def client_with_allowed():
    with TestClient(_make_app(["https://trusted.example.com"])) as c:
        yield c


@pytest.fixture
def client_empty():
    with TestClient(_make_app([])) as c:
        yield c


def test_origin_present_and_allowed(client_with_allowed):
    resp = client_with_allowed.get("/mcp/", headers={"Origin": "https://trusted.example.com"})
    assert resp.status_code == 200


def test_origin_present_and_disallowed(client_with_allowed):
    resp = client_with_allowed.get("/mcp/", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Origin not allowed"


def test_origin_absent_passes(client_with_allowed):
    resp = client_with_allowed.get("/mcp/")
    assert resp.status_code == 200


def test_origin_absent_empty_allowlist_passes(client_empty):
    resp = client_empty.get("/mcp/")
    assert resp.status_code == 200


def test_origin_present_empty_allowlist_rejected(client_empty):
    resp = client_empty.get("/mcp/", headers={"Origin": "https://any.example.com"})
    assert resp.status_code == 403


def test_non_mcp_path_ignores_origin(client_with_allowed):
    resp = client_with_allowed.get("/health", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 200
