import json
import time

import fakeredis.aioredis as fakeredis
import httpx
import pytest
import respx
from cryptography.fernet import Fernet


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("app.config.settings.GOOGLE_REDIRECT_URI", "http://localhost/callback")
    return key


@pytest.mark.asyncio
@respx.mock
async def test_get_valid_token_refresh_revoked(redis, monkeypatch):
    import app.integrations.google.token_store as token_store_module
    from app.integrations.google.token_store import OAuthRefreshError, get_valid_google_token

    key = Fernet.generate_key()
    fernet = Fernet(key)
    monkeypatch.setattr(token_store_module, "_fernet", lambda: fernet)
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


@pytest.mark.asyncio
async def test_get_valid_token_still_valid(redis, encryption_key):
    from app.integrations.google.token_store import get_valid_google_token

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
    from app.integrations.google.token_store import get_valid_google_token

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
    from app.integrations.google.token_store import OAuthTokenNotFoundError, get_valid_google_token

    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthTokenNotFoundError):
            await get_valid_google_token("user-never-authed", redis, client)
