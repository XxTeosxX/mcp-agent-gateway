import json
import os

import httpx

from app.config import settings
from app.integrations.slack.constants import (
    SLACK_AUTH_URL,
    SLACK_BOT_SCOPES,
    SLACK_TOKEN_URL,
    SLACK_USER_SCOPES,
    STATE_TTL,
)
from app.integrations.slack.token_store import persist_tokens
from app.shared.store import Store


class OAuthStateError(Exception):
    pass


async def build_authorization_url(user_id: str, store: Store) -> tuple[str, str]:
    state = os.urandom(16).hex()
    await store.set(state, json.dumps({"user_id": user_id}), ttl=STATE_TTL)

    params = {
        "client_id": settings.SLACK_CLIENT_ID,
        "scope": SLACK_BOT_SCOPES,
        "user_scope": SLACK_USER_SCOPES,
        "redirect_uri": settings.SLACK_REDIRECT_URI,
        "state": state,
    }
    url = httpx.URL(SLACK_AUTH_URL).copy_with(params=params)
    return str(url), state


async def handle_callback(
    state: str,
    code: str,
    http_client: httpx.AsyncClient,
    state_store: Store,
    token_store: Store,
) -> str:
    raw = await state_store.pop(state)
    if raw is None:
        raise OAuthStateError("State not found or expired")

    user_id: str = json.loads(raw)["user_id"]

    resp = await http_client.post(
        SLACK_TOKEN_URL,
        data={
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.SLACK_REDIRECT_URI,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    if not tokens.get("ok"):
        raise OAuthStateError(f"Slack OAuth failed: {tokens.get('error')}")

    await persist_tokens(user_id, tokens, token_store)
    return user_id
