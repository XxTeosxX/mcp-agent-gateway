import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.gateway.context import current_user_id
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
