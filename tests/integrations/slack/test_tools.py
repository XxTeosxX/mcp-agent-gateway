import json

import pytest
from cryptography.fernet import Fernet

from app.integrations.slack.slack_client import SlackAPIError, SlackClient
from app.integrations.slack.token_store import _SLACK_SHARED_USER
from app.integrations.slack.tools import (
    SLACK_TOOLS,
    build_slack_registry,
    handle_slack_search_messages,
    handle_slack_send_message,
)
from app.shared.store import InMemoryStore


@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())


@pytest.fixture
def slack_client():
    return SlackClient(timeout=10.0, max_retries=3)


@pytest.fixture
def token_store():
    return InMemoryStore()


async def _authorize(store, fernet):
    await store.set(
        _SLACK_SHARED_USER,
        json.dumps(
            {
                "bot_token_enc": fernet.encrypt(b"xoxb-bot").decode(),
                "user_token_enc": fernet.encrypt(b"xoxp-user").decode(),
                "team_id": "T1",
            }
        ),
    )


def test_registry_and_contracts_exposed():
    names = {t.name for t in SLACK_TOOLS}
    assert names == {"slack-send-message", "slack-search-messages"}


@pytest.mark.asyncio
async def test_send_message_invalid_input_returns_error(slack_client, token_store, fernet):
    result = await handle_slack_send_message(
        {"channel": "C1"}, slack_client=slack_client, token_store=token_store, fernet=fernet
    )
    assert result.isError is True


@pytest.mark.asyncio
async def test_send_message_not_authorized(slack_client, token_store, fernet):
    result = await handle_slack_send_message(
        {"channel": "C1", "text": "hi"}, slack_client=slack_client, token_store=token_store, fernet=fernet
    )
    assert result.isError is True
    assert "not authorized" in result.content[0].text


@pytest.mark.asyncio
async def test_send_message_happy_path(token_store, fernet):
    await _authorize(token_store, fernet)

    class FakeSlackClient:
        async def post_message(self, token, channel, text):
            assert token == "xoxb-bot"
            return {"ok": True, "channel": channel, "ts": "1.2"}

    result = await handle_slack_send_message(
        {"channel": "C1", "text": "hi"}, slack_client=FakeSlackClient(), token_store=token_store, fernet=fernet
    )
    assert result.isError is not True
    assert json.loads(result.content[0].text)["ts"] == "1.2"


@pytest.mark.asyncio
async def test_send_message_slack_error_returns_error(token_store, fernet):
    await _authorize(token_store, fernet)

    class FakeSlackClient:
        async def post_message(self, token, channel, text):
            raise SlackAPIError("not_in_channel")

    result = await handle_slack_send_message(
        {"channel": "C1", "text": "hi"}, slack_client=FakeSlackClient(), token_store=token_store, fernet=fernet
    )
    assert result.isError is True
    assert "not_in_channel" in result.content[0].text


@pytest.mark.asyncio
async def test_search_messages_happy_path(token_store, fernet):
    await _authorize(token_store, fernet)

    class FakeSlackClient:
        async def search_messages(self, token, query, count):
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

    result = await handle_slack_search_messages(
        {"query": "found"}, slack_client=FakeSlackClient(), token_store=token_store, fernet=fernet
    )
    assert result.isError is not True
    rows = json.loads(result.content[0].text)
    assert rows[0]["channel"] == "general"
    assert rows[0]["permalink"] == "https://slack.com/p/1"


@pytest.mark.asyncio
async def test_search_messages_invalid_input_returns_error(slack_client, token_store, fernet):
    result = await handle_slack_search_messages({}, slack_client=slack_client, token_store=token_store, fernet=fernet)
    assert result.isError is True


@pytest.mark.asyncio
async def test_search_messages_slack_error_returns_error(token_store, fernet):
    await _authorize(token_store, fernet)

    class FakeSlackClient:
        async def search_messages(self, token, query, count):
            raise SlackAPIError("not_authed")

    result = await handle_slack_search_messages(
        {"query": "x"}, slack_client=FakeSlackClient(), token_store=token_store, fernet=fernet
    )
    assert result.isError is True
    assert "not_authed" in result.content[0].text


def test_build_slack_registry_wraps_with_usage(slack_client, token_store, fernet):
    registry = build_slack_registry(slack_client=slack_client, token_store=token_store, fernet=fernet, redis=None)
    assert set(registry) == {"slack-send-message", "slack-search-messages"}
    for handler in registry.values():
        assert hasattr(handler, "__wrapped__")
