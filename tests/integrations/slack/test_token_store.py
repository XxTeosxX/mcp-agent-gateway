import json

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
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


@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())


@pytest.mark.asyncio
async def test_missing_user_raises(store, fernet):
    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token("nobody", "bot", store, fernet)


@pytest.mark.asyncio
async def test_unknown_token_type_raises(store, fernet):
    await seed_shared_slack_tokens_if_absent(store, fernet, "xoxb-bot", "xoxp-user")
    with pytest.raises(ValueError, match="Unknown token_type"):
        await get_valid_slack_token(_SLACK_SHARED_USER, "workspace", store, fernet)


@pytest.mark.asyncio
async def test_get_valid_slack_token_missing_key_raises_not_found(store, fernet):
    # bot token only — user_token_enc absent
    await store.set("shared", json.dumps({"bot_token_enc": fernet.encrypt(b"xoxb-x").decode()}))

    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token("shared", "user", store, fernet)


@pytest.mark.asyncio
async def test_seed_writes_both_tokens(store, fernet):
    await seed_shared_slack_tokens_if_absent(store, fernet, "xoxb-bot", "xoxp-user")

    assert await get_valid_slack_token(_SLACK_SHARED_USER, "bot", store, fernet) == "xoxb-bot"
    assert await get_valid_slack_token(_SLACK_SHARED_USER, "user", store, fernet) == "xoxp-user"
    # encrypted at rest — plaintext never stored
    raw = await store.get(_SLACK_SHARED_USER)
    assert "xoxb-bot" not in raw
    assert "xoxp-user" not in raw


@pytest.mark.asyncio
async def test_seed_noop_when_env_empty(store, fernet):
    await seed_shared_slack_tokens_if_absent(store, fernet, "", "")
    assert await store.get(_SLACK_SHARED_USER) is None


@pytest.mark.asyncio
async def test_seed_noop_when_already_present(store, fernet):
    await store.set(_SLACK_SHARED_USER, json.dumps({"bot_token_enc": "preexisting"}))

    await seed_shared_slack_tokens_if_absent(store, fernet, "xoxb-new", "")

    assert json.loads(await store.get(_SLACK_SHARED_USER)) == {"bot_token_enc": "preexisting"}


@pytest.mark.asyncio
async def test_seed_partial_bot_only(store, fernet):
    await seed_shared_slack_tokens_if_absent(store, fernet, "xoxb-bot", "")

    assert await get_valid_slack_token(_SLACK_SHARED_USER, "bot", store, fernet) == "xoxb-bot"
    with pytest.raises(SlackTokenNotFoundError):
        await get_valid_slack_token(_SLACK_SHARED_USER, "user", store, fernet)
