import json

import pytest
from cryptography.fernet import Fernet

from app.gateway.context import current_user_id
from app.gateway.tools.slack_tools import (
    SLACK_REGISTRY,
    SLACK_TOOLS,
    handle_slack_search_messages,
    handle_slack_send_message,
)
from app.integrations.slack.slack_client import SlackAPIError, slack_client
from app.integrations.slack.token_store import persist_tokens
from app.shared.store import InMemoryStore, slack_token_store


@pytest.fixture(autouse=True)
def slack_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.SLACK_TOKEN_ENCRYPTION_KEY", key)


@pytest.fixture
def authorized_user(monkeypatch):
    store = InMemoryStore()
    slack_token_store.init(store)
    token = current_user_id.set("user-1")
    yield store
    current_user_id.reset(token)


async def _authorize(store):
    await persist_tokens(
        "user-1",
        {
            "ok": True,
            "access_token": "xoxb-bot",
            "authed_user": {"access_token": "xoxp-user"},
            "team": {"id": "T1"},
        },
        store,
    )


def test_registry_and_contracts_exposed():
    names = {t.name for t in SLACK_TOOLS}
    assert names == {"slack-send-message", "slack-search-messages"}
    assert set(SLACK_REGISTRY) == names


@pytest.mark.asyncio
async def test_send_message_invalid_input_returns_error():
    result = await handle_slack_send_message({"channel": "C1"})
    assert result.isError is True


@pytest.mark.asyncio
async def test_send_message_not_authorized():
    slack_token_store.init(InMemoryStore())
    token = current_user_id.set("user-nobody")
    try:
        result = await handle_slack_send_message({"channel": "C1", "text": "hi"})
    finally:
        current_user_id.reset(token)
    assert result.isError is True
    assert "not authorized" in result.content[0].text


@pytest.mark.asyncio
async def test_send_message_happy_path(authorized_user, monkeypatch):
    await _authorize(authorized_user)

    async def fake_post(token, channel, text):
        assert token == "xoxb-bot"
        return {"ok": True, "channel": channel, "ts": "1.2"}

    monkeypatch.setattr(slack_client, "post_message", fake_post)
    result = await handle_slack_send_message({"channel": "C1", "text": "hi"})
    assert result.isError is not True
    assert json.loads(result.content[0].text)["ts"] == "1.2"


@pytest.mark.asyncio
async def test_send_message_slack_error_returns_error(authorized_user, monkeypatch):
    await _authorize(authorized_user)

    async def fake_post(token, channel, text):
        raise SlackAPIError("not_in_channel")

    monkeypatch.setattr(slack_client, "post_message", fake_post)
    result = await handle_slack_send_message({"channel": "C1", "text": "hi"})
    assert result.isError is True
    assert "not_in_channel" in result.content[0].text


@pytest.mark.asyncio
async def test_search_messages_happy_path(authorized_user, monkeypatch):
    await _authorize(authorized_user)

    async def fake_search(token, query, count):
        assert token == "xoxp-user"
        return [
            {
                "text": "found it",
                "channel": {"id": "C1", "name": "general"},
                "user": "U1",
                "ts": "9.9",
                "permalink": "https://slack.com/p/1",
            }
        ]

    monkeypatch.setattr(slack_client, "search_messages", fake_search)
    result = await handle_slack_search_messages({"query": "found"})
    assert result.isError is not True
    rows = json.loads(result.content[0].text)
    assert rows[0]["channel"] == "general"
    assert rows[0]["permalink"] == "https://slack.com/p/1"


@pytest.mark.asyncio
async def test_search_messages_invalid_input_returns_error():
    result = await handle_slack_search_messages({})
    assert result.isError is True


@pytest.mark.asyncio
async def test_search_messages_slack_error_returns_error(authorized_user, monkeypatch):
    await _authorize(authorized_user)

    async def fake_search(token, query, count):
        raise SlackAPIError("not_authed")

    monkeypatch.setattr(slack_client, "search_messages", fake_search)
    result = await handle_slack_search_messages({"query": "x"})
    assert result.isError is True
    assert "not_authed" in result.content[0].text
