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
    seed_refresh_token,
    seed_shared_token_if_absent,
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
@respx.mock
async def test_expired_token_refreshes(store, encryption_key):
    enc = Fernet(encryption_key.encode()).encrypt(b"rt-2").decode()
    await store.set("user-2", json.dumps({"access_token": "old", "refresh_token_enc": enc, "expires_at": 0}))
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
async def test_revoked_refresh_raises(store, encryption_key):
    enc = Fernet(encryption_key.encode()).encrypt(b"rt-3").decode()
    await store.set("user-3", json.dumps({"access_token": "old", "refresh_token_enc": enc, "expires_at": 0}))
    respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthRefreshError):
            await get_valid_google_token("user-3", client, store)


@pytest.mark.asyncio
async def test_seed_refresh_token_stores_expired_and_encrypted(store, encryption_key):
    await seed_refresh_token("rt-seed", store)
    data = json.loads(await store.get("google:shared"))
    assert data["expires_at"] == 0
    assert data["access_token"] == ""
    decrypted = Fernet(encryption_key.encode()).decrypt(data["refresh_token_enc"].encode()).decode()
    assert decrypted == "rt-seed"


@pytest.mark.asyncio
async def test_seed_if_absent_writes_when_env_set_and_key_missing(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_SHARED_REFRESH_TOKEN", "rt-env")
    await seed_shared_token_if_absent(store)
    assert await store.get("google:shared") is not None


@pytest.mark.asyncio
async def test_seed_if_absent_skips_when_env_empty(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_SHARED_REFRESH_TOKEN", "")
    await seed_shared_token_if_absent(store)
    assert await store.get("google:shared") is None


@pytest.mark.asyncio
async def test_seed_if_absent_does_not_overwrite_existing(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_SHARED_REFRESH_TOKEN", "rt-env")
    await store.set("google:shared", json.dumps({"access_token": "keep", "refresh_token_enc": "x", "expires_at": 0}))
    await seed_shared_token_if_absent(store)
    assert json.loads(await store.get("google:shared"))["access_token"] == "keep"


@pytest.mark.asyncio
@respx.mock
async def test_seeded_token_refreshes_on_first_use(store):
    await seed_refresh_token("rt-seed", store)
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("google:shared", client, store)
    assert token == "fresh"
