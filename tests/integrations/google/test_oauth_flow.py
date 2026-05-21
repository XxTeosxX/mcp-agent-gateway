import json

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.integrations.google.oauth_flow import (
    OAuthStateError,
    build_authorization_url,
    handle_callback,
)
from app.shared.store import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture(autouse=True)
def google_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("app.config.settings.GOOGLE_REDIRECT_URI", "http://localhost/callback")


@pytest.mark.asyncio
async def test_build_authorization_url_stores_state(store):
    url, state = await build_authorization_url("user-abc", store)
    assert "accounts.google.com" in url
    assert "code_challenge" in url
    assert len(state) == 32
    raw = await store.get(state)
    assert raw is not None
    data = json.loads(raw)
    assert data["user_id"] == "user-abc"
    assert "code_verifier" in data


@pytest.fixture
def token_store():
    return InMemoryStore()


@pytest.mark.asyncio
async def test_handle_callback_unknown_state_raises(store, token_store):
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthStateError):
            await handle_callback("nope", "code", client, store, token_store)


@pytest.mark.asyncio
@respx.mock
async def test_handle_callback_exchanges_and_persists(store, token_store):
    _, state = await build_authorization_url("user-xyz", store)
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as client:
        user_id = await handle_callback(state, "the-code", client, store, token_store)
    assert user_id == "user-xyz"
    assert await store.get(state) is None
    assert await token_store.get("user-xyz") is not None
