import json
import time

import httpx
from cryptography.fernet import Fernet

from app.config import settings

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuthTokenNotFoundError(Exception):
    pass


class OAuthRefreshError(Exception):
    pass


def _fernet() -> Fernet:
    return Fernet(settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())


async def persist_tokens(user_id: str, tokens: dict, redis) -> None:
    refresh_token = tokens["refresh_token"]
    refresh_token_enc = _fernet().encrypt(refresh_token.encode()).decode()
    expires_at = time.time() + tokens.get("expires_in", 3600)
    await redis.set(
        f"google:token:{user_id}",
        json.dumps(
            {
                "access_token": tokens["access_token"],
                "refresh_token_enc": refresh_token_enc,
                "expires_at": expires_at,
            }
        ),
    )


async def get_valid_google_token(user_id: str, redis, http_client: httpx.AsyncClient) -> str:
    raw = await redis.get(f"google:token:{user_id}")
    if raw is None:
        raise OAuthTokenNotFoundError("User has not authorized Google")

    data = json.loads(raw)

    if data["expires_at"] - 60 > time.time():
        return data["access_token"]

    refresh_token = _fernet().decrypt(data["refresh_token_enc"].encode()).decode()
    resp = await http_client.post(
        _GOOGLE_TOKEN_URL,
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
    await redis.set(f"google:token:{user_id}", json.dumps(data))

    return data["access_token"]
