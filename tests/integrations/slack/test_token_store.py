import inspect
import json

import pytest
from cryptography.fernet import Fernet

from app.config import Settings, settings
from app.integrations.slack.token_store import (
    _SLACK_SHARED_USER,
    SlackTokenNotFoundError,
    get_valid_slack_token,
    seed_shared_slack_tokens_if_absent,
)
from app.shared.store import InMemoryStore


def test_shared_token_settings_exist_with_empty_defaults():
    fields = Settings.model_fields
    assert "SLACK_SHARED_BOT_TOKEN" in fields
    assert "SLACK_SHARED_USER_TOKEN" in fields
    assert fields["SLACK_SHARED_BOT_TOKEN"].default == ""
    assert fields["SLACK_SHARED_USER_TOKEN"].default == ""


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture(autouse=True)
def slack_settings(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.SLACK_TOKEN_ENCRYPTION_KEY", key)


@pytest.mark.asyncio
async def test_missing_user_raises(store):
    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token("nobody", "bot", store)


@pytest.mark.asyncio
async def test_unknown_token_type_raises(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_BOT_TOKEN", "xoxb-bot")
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_USER_TOKEN", "xoxp-user")
    await seed_shared_slack_tokens_if_absent(store)
    with pytest.raises(ValueError, match="Unknown token_type"):
        await get_valid_slack_token(_SLACK_SHARED_USER, "workspace", store)


@pytest.mark.asyncio
async def test_get_valid_slack_token_missing_key_raises_not_found(store):
    f = Fernet(settings.SLACK_TOKEN_ENCRYPTION_KEY.encode())
    # bot token only — user_token_enc absent
    await store.set("shared", json.dumps({"bot_token_enc": f.encrypt(b"xoxb-x").decode()}))

    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token("shared", "user", store)


@pytest.mark.asyncio
async def test_seed_writes_both_tokens(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_BOT_TOKEN", "xoxb-bot")
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_USER_TOKEN", "xoxp-user")

    await seed_shared_slack_tokens_if_absent(store)

    assert await get_valid_slack_token(_SLACK_SHARED_USER, "bot", store) == "xoxb-bot"
    assert await get_valid_slack_token(_SLACK_SHARED_USER, "user", store) == "xoxp-user"
    # encrypted at rest — plaintext never stored
    raw = await store.get(_SLACK_SHARED_USER)
    assert "xoxb-bot" not in raw
    assert "xoxp-user" not in raw


@pytest.mark.asyncio
async def test_seed_noop_when_env_empty(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_BOT_TOKEN", "")
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_USER_TOKEN", "")

    await seed_shared_slack_tokens_if_absent(store)

    assert await store.get(_SLACK_SHARED_USER) is None


@pytest.mark.asyncio
async def test_seed_noop_when_already_present(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_BOT_TOKEN", "xoxb-new")
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_USER_TOKEN", "")
    await store.set(_SLACK_SHARED_USER, json.dumps({"bot_token_enc": "preexisting"}))

    await seed_shared_slack_tokens_if_absent(store)

    assert json.loads(await store.get(_SLACK_SHARED_USER)) == {"bot_token_enc": "preexisting"}


@pytest.mark.asyncio
async def test_seed_partial_bot_only(store, monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_BOT_TOKEN", "xoxb-bot")
    monkeypatch.setattr("app.config.settings.SLACK_SHARED_USER_TOKEN", "")

    await seed_shared_slack_tokens_if_absent(store)

    assert await get_valid_slack_token(_SLACK_SHARED_USER, "bot", store) == "xoxb-bot"
    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token(_SLACK_SHARED_USER, "user", store)


def test_lifespan_seeds_shared_slack_tokens():
    from app.mcp import app as mcp_app_module

    src = inspect.getsource(mcp_app_module.mcp_lifespan)
    assert "seed_shared_slack_tokens_if_absent" in src
