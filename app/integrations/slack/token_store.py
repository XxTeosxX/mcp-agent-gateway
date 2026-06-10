import json

from cryptography.fernet import Fernet

from app.config import settings
from app.shared.store import Store


def _fernet() -> Fernet:
    return Fernet(settings.SLACK_TOKEN_ENCRYPTION_KEY.encode())


class SlackTokenNotFoundError(Exception):
    pass


async def persist_tokens(user_id: str, tokens: dict, store: Store) -> None:
    f = _fernet()
    bot_token = tokens["access_token"]
    user_token = tokens["authed_user"]["access_token"]
    await store.set(
        user_id,
        json.dumps(
            {
                "bot_token_enc": f.encrypt(bot_token.encode()).decode(),
                "user_token_enc": f.encrypt(user_token.encode()).decode(),
                "team_id": tokens.get("team", {}).get("id", ""),
            }
        ),
    )


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
    return _fernet().decrypt(data[key].encode()).decode()
