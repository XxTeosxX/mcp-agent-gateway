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


@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())


@pytest.fixture
def client_id():
    return "test-client-id"


@pytest.fixture
def client_secret():
    return "test-secret"


@pytest.mark.asyncio
async def test_not_authorized_raises(store, fernet, client_id, client_secret):
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthTokenNotFoundError):
            await get_valid_google_token("user-x", client, store, fernet, client_id, client_secret)


@pytest.mark.asyncio
@respx.mock
async def test_expired_token_refreshes(store, fernet, client_id, client_secret):
    enc = fernet.encrypt(b"rt-2").decode()
    await store.set("user-2", json.dumps({"access_token": "old", "refresh_token_enc": enc, "expires_at": 0}))
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("user-2", client, store, fernet, client_id, client_secret)
    assert token == "new"
    raw = await store.get("user-2")
    assert json.loads(raw)["access_token"] == "new"


@pytest.mark.asyncio
@respx.mock
async def test_revoked_refresh_raises(store, fernet, client_id, client_secret):
    enc = fernet.encrypt(b"rt-3").decode()
    await store.set("user-3", json.dumps({"access_token": "old", "refresh_token_enc": enc, "expires_at": 0}))
    respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthRefreshError):
            await get_valid_google_token("user-3", client, store, fernet, client_id, client_secret)


@pytest.mark.asyncio
async def test_seed_refresh_token_stores_expired_and_encrypted(store, fernet):
    await seed_refresh_token("rt-seed", store, fernet)
    data = json.loads(await store.get("google:shared"))
    assert data["expires_at"] == 0
    assert data["access_token"] == ""
    decrypted = fernet.decrypt(data["refresh_token_enc"].encode()).decode()
    assert decrypted == "rt-seed"


@pytest.mark.asyncio
async def test_seed_if_absent_writes_when_env_set_and_key_missing(store, fernet):
    await seed_shared_token_if_absent(store, fernet, "rt-env")
    assert await store.get("google:shared") is not None


@pytest.mark.asyncio
async def test_seed_if_absent_skips_when_env_empty(store, fernet):
    await seed_shared_token_if_absent(store, fernet, "")
    assert await store.get("google:shared") is None


@pytest.mark.asyncio
async def test_seed_if_absent_does_not_overwrite_existing(store, fernet):
    await store.set("google:shared", json.dumps({"access_token": "keep", "refresh_token_enc": "x", "expires_at": 0}))
    await seed_shared_token_if_absent(store, fernet, "rt-env")
    assert json.loads(await store.get("google:shared"))["access_token"] == "keep"


@pytest.mark.asyncio
@respx.mock
async def test_seeded_token_refreshes_on_first_use(store, fernet, client_id, client_secret):
    await seed_refresh_token("rt-seed", store, fernet)
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    )
    async with httpx.AsyncClient() as client:
        token = await get_valid_google_token("google:shared", client, store, fernet, client_id, client_secret)
    assert token == "fresh"
