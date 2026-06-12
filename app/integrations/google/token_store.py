import json
import time

import httpx
from cryptography.fernet import Fernet

from app.config import settings
from app.integrations.google.constants import GOOGLE_TOKEN_URL
from app.shared.store import Store

_GOOGLE_SHARED_USER = "google:shared"


def _fernet() -> Fernet:
    return Fernet(settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())


class OAuthTokenNotFoundError(Exception):
    pass


class OAuthRefreshError(Exception):
    pass


async def get_valid_google_token(user_id: str, http_client: httpx.AsyncClient, store: Store) -> str:
    raw = await store.get(user_id)
    if raw is None:
        raise OAuthTokenNotFoundError("User has not authorized Google")

    data = json.loads(raw)

    if data["expires_at"] - 60 > time.time():
        return data["access_token"]

    refresh_token = _fernet().decrypt(data["refresh_token_enc"].encode()).decode()
    resp = await http_client.post(
        GOOGLE_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
        },
    )

    if resp.status_code in (400, 401):
        try:
            body = resp.json()
            if body.get("error") in ("invalid_grant", "token_revoked"):
                raise OAuthRefreshError("Google refresh token revoked")
        except (ValueError, KeyError):
            pass
    resp.raise_for_status()
    tokens = resp.json()

    data["access_token"] = tokens["access_token"]
    data["expires_at"] = time.time() + tokens.get("expires_in", 3600)
    await store.set(user_id, json.dumps(data))

    return data["access_token"]


async def seed_refresh_token(refresh_token: str, store: Store) -> None:
    """Persist a bare refresh token so the next Drive call triggers a refresh.

    Stores expires_at=0 (already expired) and an empty access_token, so
    get_valid_google_token refreshes against Google on first use.
    """
    refresh_token_enc = _fernet().encrypt(refresh_token.encode()).decode()
    await store.set(
        _GOOGLE_SHARED_USER,
        json.dumps({"access_token": "", "refresh_token_enc": refresh_token_enc, "expires_at": 0}),
    )


async def seed_shared_token_if_absent(store: Store) -> None:
    """Seed token:google:shared from settings.GOOGLE_SHARED_REFRESH_TOKEN.

    No-op when the env var is empty or a token already exists (rotation-safe).
    """
    if not settings.GOOGLE_SHARED_REFRESH_TOKEN:
        return
    if await store.get(_GOOGLE_SHARED_USER) is not None:
        return
    await seed_refresh_token(settings.GOOGLE_SHARED_REFRESH_TOKEN, store)
