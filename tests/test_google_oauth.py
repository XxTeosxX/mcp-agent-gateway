import json
import time
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis as fakeredis
import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_google_settings_exist():
    assert hasattr(settings, "GOOGLE_CLIENT_ID")
    assert hasattr(settings, "GOOGLE_CLIENT_SECRET")
    assert hasattr(settings, "GOOGLE_TOKEN_ENCRYPTION_KEY")
    assert hasattr(settings, "GOOGLE_REDIRECT_URI")


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_build_authorization_url_stores_state(redis):
    from app.google.oauth import build_authorization_url

    url, state = await build_authorization_url("user-abc", redis)
    assert "accounts.google.com" in url
    assert "code_challenge" in url
    assert len(state) == 32
    raw = await redis.get(f"google:state:{state}")
    assert raw is not None
    data = json.loads(raw)
    assert data["user_id"] == "user-abc"
    assert "code_verifier" in data


@pytest.mark.asyncio
async def test_build_authorization_url_state_ttl(redis):
    from app.google.oauth import build_authorization_url

    _, state = await build_authorization_url("user-abc", redis)
    ttl = await redis.ttl(f"google:state:{state}")
    assert 590 <= ttl <= 600


@pytest.mark.asyncio
@respx.mock
async def test_get_valid_token_refresh_revoked(redis, monkeypatch):
    from app.google import oauth as oauth_module
    from app.google.oauth import OAuthRefreshError, get_valid_google_token

    key = Fernet.generate_key()
    fernet = Fernet(key)
    monkeypatch.setattr(oauth_module, "_fernet", lambda: fernet)
    refresh_token_enc = fernet.encrypt(b"old-refresh-token").decode()

    await redis.set(
        "google:token:user-xyz",
        json.dumps(
            {
                "access_token": "old-access-token",
                "refresh_token_enc": refresh_token_enc,
                "expires_at": time.time() - 100,
            }
        ),
    )

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthRefreshError):
            await get_valid_google_token("user-xyz", redis, client)


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("app.config.settings.GOOGLE_REDIRECT_URI", "http://localhost/callback")
    return key


@pytest.mark.asyncio
async def test_handle_callback_valid_state(redis, encryption_key):
    from app.google.oauth import build_authorization_url, handle_callback

    _, state = await build_authorization_url("user-123", redis)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.test",
                    "refresh_token": "1//test-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        )
        async with httpx.AsyncClient() as client:
            user_id = await handle_callback(state, "auth-code-abc", redis, client)

    assert user_id == "user-123"
    raw = await redis.get("google:token:user-123")
    data = json.loads(raw)
    assert data["access_token"] == "ya29.test"
    assert data["refresh_token_enc"] != "1//test-refresh"
    decrypted = Fernet(encryption_key.encode()).decrypt(data["refresh_token_enc"].encode()).decode()
    assert decrypted == "1//test-refresh"


@pytest.mark.asyncio
async def test_handle_callback_invalid_state(redis, encryption_key):
    from app.google.oauth import OAuthStateError, handle_callback

    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthStateError):
            await handle_callback("nonexistent-state", "code", redis, client)


@pytest.mark.asyncio
async def test_get_valid_token_still_valid(redis, encryption_key):
    from app.google.oauth import get_valid_google_token

    key = Fernet(encryption_key.encode())
    refresh_enc = key.encrypt(b"refresh-token").decode()
    await redis.set(
        "google:token:user-123",
        json.dumps(
            {
                "access_token": "ya29.still-valid",
                "refresh_token_enc": refresh_enc,
                "expires_at": time.time() + 3000,
            }
        ),
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("user-123", redis, client)
    assert token == "ya29.still-valid"


@pytest.mark.asyncio
async def test_get_valid_token_refreshes_expired(redis, encryption_key):
    from app.google.oauth import get_valid_google_token

    key = Fernet(encryption_key.encode())
    refresh_enc = key.encrypt(b"old-refresh").decode()
    await redis.set(
        "google:token:user-123",
        json.dumps(
            {
                "access_token": "ya29.expired",
                "refresh_token_enc": refresh_enc,
                "expires_at": time.time() - 10,
            }
        ),
    )
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.new",
                    "expires_in": 3600,
                },
            )
        )
        async with httpx.AsyncClient() as client:
            token = await get_valid_google_token("user-123", redis, client)
    assert token == "ya29.new"


@pytest.mark.asyncio
async def test_get_valid_token_not_found(redis, encryption_key):
    from app.google.oauth import OAuthTokenNotFoundError, get_valid_google_token

    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthTokenNotFoundError):
            await get_valid_google_token("user-never-authed", redis, client)


@pytest.fixture
def api_client():
    return TestClient(app)


def test_initiate_without_auth(api_client):
    resp = api_client.post("/auth/google/initiate")
    assert resp.status_code == 401


def test_initiate_with_auth(api_client, rsa_key):
    from tests.conftest import make_token

    token = make_token(rsa_key)
    with patch(
        "app.routers.google.build_authorization_url",
        new=AsyncMock(return_value=("https://accounts.google.com/o/oauth2/v2/auth?state=abc", "abc")),
    ):
        with patch("app.routers.google._get_redis", return_value=AsyncMock()):
            resp = api_client.post(
                "/auth/google/initiate",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    assert "state" in body
