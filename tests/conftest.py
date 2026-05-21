import os

os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_validator(private_key):
    public_key = private_key.public_key()

    def validate(_, token: str) -> dict:
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.OAUTH_ISSUER_URL,
            audience=settings.OAUTH_EXPECTED_AUDIENCE,
        )

    return validate


def make_token(key, **overrides) -> str:
    payload = {
        "sub": "user-123",
        "iss": settings.OAUTH_ISSUER_URL,
        "aud": settings.OAUTH_EXPECTED_AUDIENCE,
        "exp": int(time.time()) + 300,
        "scope": "mcp:tools:read mcp:tools:write",
        **overrides,
    }
    return jwt.encode(payload, key, algorithm="RS256")


@pytest.fixture(scope="session", autouse=True)
def mock_token_validator(rsa_key):
    with patch("app.identity.token_validator.TokenValidator.validate", _make_validator(rsa_key)):
        yield


@pytest.fixture
def _fake_redis():
    return FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_get_redis(_fake_redis):
    async def _get_redis(_url):
        await _fake_redis.ping()
        return _fake_redis

    with patch("app.main.get_redis", _get_redis):
        yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
