import json

from cryptography.fernet import Fernet

from app.config import settings
from app.shared.exceptions import UpstreamAuthError
from app.shared.store import Store, StoreHolder

_SLACK_SHARED_USER = "shared"


def _fernet() -> Fernet:
    return Fernet(settings.SLACK_TOKEN_ENCRYPTION_KEY.encode())


class SlackTokenNotFoundError(UpstreamAuthError):
    pass


async def get_valid_slack_token(user_id: str, token_type: str, store: Store) -> str:
    raw = await store.get(user_id)
    if raw is None:
        raise SlackTokenNotFoundError("User has not authorized Slack")
    data = json.loads(raw)
    if token_type == "bot":
        key = "bot_token_enc"
    elif token_type == "user":
        key = "user_token_enc"
    else:
        raise ValueError(f"Unknown token_type: {token_type!r}. Expected 'bot' or 'user'.")
    if key not in data:
        raise SlackTokenNotFoundError(f"Slack {token_type} token not provisioned")
    return _fernet().decrypt(data[key].encode()).decode()


async def seed_shared_slack_tokens_if_absent(store: Store) -> None:
    """Seed slack:token:shared from SLACK_SHARED_{BOT,USER}_TOKEN.

    No-op when both env vars are empty or a token already exists (rotation-safe).
    Encrypts only the keys provided.
    """
    if not settings.SLACK_SHARED_BOT_TOKEN and not settings.SLACK_SHARED_USER_TOKEN:
        return
    if await store.get(_SLACK_SHARED_USER) is not None:
        return

    f = _fernet()
    data: dict = {"team_id": ""}
    if settings.SLACK_SHARED_BOT_TOKEN:
        data["bot_token_enc"] = f.encrypt(settings.SLACK_SHARED_BOT_TOKEN.encode()).decode()
    if settings.SLACK_SHARED_USER_TOKEN:
        data["user_token_enc"] = f.encrypt(settings.SLACK_SHARED_USER_TOKEN.encode()).decode()
    await store.set(_SLACK_SHARED_USER, json.dumps(data))


slack_token_store = StoreHolder()
