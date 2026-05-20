import json

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
async def test_build_authorization_url_stores_state(redis):
    from app.integrations.google.oauth_flow import build_authorization_url

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
    from app.integrations.google.oauth_flow import build_authorization_url

    _, state = await build_authorization_url("user-abc", redis)
    ttl = await redis.ttl(f"google:state:{state}")
    assert 590 <= ttl <= 600


@pytest.mark.asyncio
async def test_handle_callback_valid_state(redis, encryption_key):
    from app.integrations.google.oauth_flow import build_authorization_url, handle_callback

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
    from app.integrations.google.oauth_flow import OAuthStateError, handle_callback

    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthStateError):
            await handle_callback("nonexistent-state", "code", redis, client)
