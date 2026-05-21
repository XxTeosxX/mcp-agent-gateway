import json

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.integrations.google.constants import GOOGLE_TOKEN_URL
from app.integrations.google.token_store import (
    OAuthRefreshError,
    OAuthTokenNotFoundError,
    get_valid_google_token,
    persist_tokens,
)
from app.shared.store import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    return key


@pytest.mark.asyncio
async def test_not_authorized_raises(store):
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthTokenNotFoundError):
            await get_valid_google_token("user-x", client, store)


@pytest.mark.asyncio
async def test_persist_then_get_valid_returns_access_token(store):
    await persist_tokens(
        "user-1",
        {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        store,
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("user-1", client, store)
    assert token == "at-1"


@pytest.mark.asyncio
@respx.mock
async def test_expired_token_refreshes(store):
    await persist_tokens(
        "user-2",
        {"access_token": "old", "refresh_token": "rt-2", "expires_in": -10},
        store,
    )
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("user-2", client, store)
    assert token == "new"
    raw = await store.get("user-2")
    assert json.loads(raw)["access_token"] == "new"


@pytest.mark.asyncio
@respx.mock
async def test_revoked_refresh_raises(store):
    await persist_tokens(
        "user-3",
        {"access_token": "old", "refresh_token": "rt-3", "expires_in": -10},
        store,
    )
    respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthRefreshError):
            await get_valid_google_token("user-3", client, store)
