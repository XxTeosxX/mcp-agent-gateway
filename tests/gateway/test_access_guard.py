import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.gateway.context import current_user_id, current_user_scopes
from app.gateway.middleware.access_guard import AccessGuard
from tests.conftest import make_token


@pytest.fixture(scope="session")
def guard_app(rsa_key: RSAPrivateKey) -> TestClient:
    _app = FastAPI()
    _app.add_middleware(AccessGuard)

    @_app.get("/probe")
    async def probe(request: Request):
        return JSONResponse({"user_id": current_user_id.get()})

    with TestClient(_app) as c:
        c.headers["Authorization"] = f"Bearer {make_token(rsa_key, sub='user-xyz')}"
        yield c


def test_current_user_id_set_after_valid_token(guard_app):
    resp = guard_app.get("/probe")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "user-xyz"


@pytest.fixture
def scope_app(rsa_key: RSAPrivateKey) -> TestClient:
    _app = FastAPI()
    _app.add_middleware(AccessGuard)

    @_app.get("/scopes")
    async def scopes(request: Request):
        return JSONResponse(
            {
                "state": sorted(request.state.user["scopes"]),
                "ctx": sorted(current_user_scopes.get()),
            }
        )

    return TestClient(_app)


def _auth(rsa_key, **overrides):
    return {"Authorization": f"Bearer {make_token(rsa_key, **overrides)}"}


def test_drive_role_normalized_to_scope(scope_app, rsa_key):
    headers = _auth(
        rsa_key,
        scope="mcp:tools:read",
        resource_access={"mcp-gateway": {"roles": ["drive-user"]}},
    )
    body = scope_app.get("/scopes", headers=headers).json()
    assert "mcp:google:read" in body["state"]
    assert "mcp:google:read" in body["ctx"]
    assert "mcp:tools:read" in body["state"]  # base scopes preserved


def test_slack_role_normalized_to_scope(scope_app, rsa_key):
    headers = _auth(rsa_key, resource_access={"mcp-gateway": {"roles": ["slack-user"]}})
    body = scope_app.get("/scopes", headers=headers).json()
    assert "mcp:slack:read" in body["ctx"]
    assert "mcp:google:read" not in body["ctx"]


def test_both_roles_normalized(scope_app, rsa_key):
    headers = _auth(
        rsa_key,
        resource_access={"mcp-gateway": {"roles": ["drive-user", "slack-user"]}},
    )
    body = scope_app.get("/scopes", headers=headers).json()
    assert {"mcp:google:read", "mcp:slack:read"} <= set(body["ctx"])


def test_no_role_no_scope(scope_app, rsa_key):
    headers = _auth(rsa_key, scope="mcp:tools:read", resource_access={})
    body = scope_app.get("/scopes", headers=headers).json()
    assert "mcp:google:read" not in body["ctx"]
    assert "mcp:slack:read" not in body["ctx"]


def test_unknown_role_ignored(scope_app, rsa_key):
    headers = _auth(rsa_key, scope="", resource_access={"mcp-gateway": {"roles": ["random-role"]}})
    body = scope_app.get("/scopes", headers=headers).json()
    assert body["ctx"] == []  # empty base scope, unknown role maps to nothing
