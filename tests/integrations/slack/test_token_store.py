import json

import pytest
from cryptography.fernet import Fernet

from app.integrations.slack.token_store import (
    SlackTokenNotFoundError,
    get_valid_slack_token,
    persist_tokens,
)
from app.shared.store import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture(autouse=True)
def slack_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.SLACK_TOKEN_ENCRYPTION_KEY", key)


def _oauth_response() -> dict:
    return {
        "ok": True,
        "access_token": "xoxb-bot-token",
        "authed_user": {"access_token": "xoxp-user-token"},
        "team": {"id": "T123"},
    }


@pytest.mark.asyncio
async def test_persist_and_get_bot_token(store):
    await persist_tokens("user-1", _oauth_response(), store)
    token = await get_valid_slack_token("user-1", "bot", store)
    assert token == "xoxb-bot-token"


@pytest.mark.asyncio
async def test_persist_and_get_user_token(store):
    await persist_tokens("user-1", _oauth_response(), store)
    token = await get_valid_slack_token("user-1", "user", store)
    assert token == "xoxp-user-token"


@pytest.mark.asyncio
async def test_tokens_encrypted_at_rest(store):
    await persist_tokens("user-1", _oauth_response(), store)
    raw = await store.get("user-1")
    data = json.loads(raw)
    assert "xoxb-bot-token" not in raw
    assert "xoxp-user-token" not in raw
    assert data["team_id"] == "T123"


@pytest.mark.asyncio
async def test_missing_user_raises(store):
    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token("nobody", "bot", store)


@pytest.mark.asyncio
async def test_unknown_token_type_raises(store):
    await persist_tokens("user-1", _oauth_response(), store)
    with pytest.raises(ValueError, match="Unknown token_type"):
        await get_valid_slack_token("user-1", "workspace", store)
