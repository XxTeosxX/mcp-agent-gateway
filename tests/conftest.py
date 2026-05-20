import os

os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
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
def client() -> TestClient:
    return TestClient(app)
