import json

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.integrations.slack.constants import SLACK_TOKEN_URL
from app.integrations.slack.oauth_flow import (
    OAuthStateError,
    build_authorization_url,
    handle_callback,
)
from app.integrations.slack.token_store import get_valid_slack_token
from app.shared.store import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture(autouse=True)
def slack_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.SLACK_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.SLACK_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.SLACK_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr("app.config.settings.SLACK_REDIRECT_URI", "http://localhost:8000/auth/slack/callback")


@pytest.mark.asyncio
async def test_build_url_has_scopes_and_no_pkce(store):
    url, state = await build_authorization_url("user-1", store)
    assert "slack.com/oauth/v2/authorize" in url
    assert "scope=chat%3Awrite%2Cchannels%3Ahistory" in url
    assert "user_scope=search%3Aread" in url
    assert f"state={state}" in url
    assert "code_challenge" not in url
    raw = await store.get(state)
    assert json.loads(raw)["user_id"] == "user-1"


@pytest.mark.asyncio
@respx.mock
async def test_handle_callback_persists_both_tokens(store):
    _, state = await build_authorization_url("user-1", store)
    respx.post(SLACK_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "access_token": "xoxb-bot",
                "authed_user": {"access_token": "xoxp-user"},
                "team": {"id": "T1"},
            },
        )
    )
    async with httpx.AsyncClient() as client:
        user_id = await handle_callback(state, "code-123", client, store, store)
    assert user_id == "user-1"
    assert await get_valid_slack_token("user-1", "bot", store) == "xoxb-bot"
    assert await get_valid_slack_token("user-1", "user", store) == "xoxp-user"


@pytest.mark.asyncio
@respx.mock
async def test_handle_callback_ok_false_raises(store):
    _, state = await build_authorization_url("user-1", store)
    respx.post(SLACK_TOKEN_URL).mock(return_value=httpx.Response(200, json={"ok": False, "error": "invalid_code"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthStateError, match="invalid_code"):
            await handle_callback(state, "bad", client, store, store)


@pytest.mark.asyncio
async def test_handle_callback_missing_state_raises(store):
    async with httpx.AsyncClient() as client:
        with pytest.raises(OAuthStateError):
            await handle_callback("nonexistent", "code", client, store, store)
