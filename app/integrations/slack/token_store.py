import json

from cryptography.fernet import Fernet

from app.shared.exceptions import UpstreamAuthError
from app.shared.store import Store

_SLACK_SHARED_USER = "shared"


class SlackTokenNotFoundError(UpstreamAuthError):
    pass


async def get_valid_slack_token(user_id: str, token_type: str, store: Store, fernet: Fernet) -> str:
    raw = await store.get(user_id)
    if raw is None:
        raise SlackTokenNotFoundError("User has not authorized Slack")
    data = json.loads(raw)
    if token_type == "bot":  # nosec B105 - discriminator value, not a secret
        key = "bot_token_enc"
    elif token_type == "user":  # nosec B105 - discriminator value, not a secret
        key = "user_token_enc"
    else:
        raise ValueError(f"Unknown token_type: {token_type!r}. Expected 'bot' or 'user'.")
    if key not in data:
        raise SlackTokenNotFoundError(f"Slack {token_type} token not provisioned")
    return fernet.decrypt(data[key].encode()).decode()


async def seed_shared_slack_tokens_if_absent(
    store: Store, fernet: Fernet, bot_token: str | None, user_token: str | None
) -> None:
    """Seed slack:token:shared from bot/user tokens.

    No-op when both tokens are empty or a token already exists (rotation-safe).
    Encrypts only the keys provided.
    """
    if not bot_token and not user_token:
        return
    if await store.get(_SLACK_SHARED_USER) is not None:
        return
    data: dict = {"team_id": ""}
    if bot_token:
        data["bot_token_enc"] = fernet.encrypt(bot_token.encode()).decode()
    if user_token:
        data["user_token_enc"] = fernet.encrypt(user_token.encode()).decode()
    await store.set(_SLACK_SHARED_USER, json.dumps(data))
