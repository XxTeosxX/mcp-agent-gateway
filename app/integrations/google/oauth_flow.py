import base64
import hashlib
import json
import os

import httpx

from app.config import settings
from app.integrations.google.token_store import persist_tokens

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_TTL = 600


class OAuthStateError(Exception):
    pass


def _generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def build_authorization_url(user_id: str, redis) -> tuple[str, str]:
    code_verifier, code_challenge = _generate_pkce()
    state = os.urandom(16).hex()

    await redis.set(
        f"google:state:{state}",
        json.dumps({"user_id": user_id, "code_verifier": code_verifier}),
        ex=_STATE_TTL,
    )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive.readonly",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    url = httpx.URL(_GOOGLE_AUTH_URL).copy_with(params=params)
    return str(url), state


async def handle_callback(state: str, code: str, redis, http_client: httpx.AsyncClient) -> str:
    raw = await redis.getdel(f"google:state:{state}")
    if raw is None:
        raise OAuthStateError("State not found or expired")

    data = json.loads(raw)
    user_id: str = data["user_id"]
    code_verifier: str = data["code_verifier"]

    resp = await http_client.post(
        _GOOGLE_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise OAuthStateError("Google did not return a refresh_token — ensure access_type=offline and prompt=consent")

    await persist_tokens(user_id, tokens, redis)
    return user_id
