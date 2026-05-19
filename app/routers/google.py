import logging

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.google.oauth import (
    OAuthStateError,
    build_authorization_url,
    handle_callback,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["google"])

_redis_instance: aioredis.Redis | None = None
_http_client: httpx.AsyncClient | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_instance


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10.0, verify=True)
    return _http_client


@router.post("/auth/google/initiate")
async def google_initiate(request: Request) -> JSONResponse:
    user_id: str = request.state.user["id"]
    redis = _get_redis()
    authorization_url, state = await build_authorization_url(user_id, redis)
    return JSONResponse({"authorization_url": authorization_url, "state": state})


@router.get("/auth/google/callback")
async def google_callback(state: str, code: str) -> JSONResponse:
    redis = _get_redis()
    client = _get_http_client()
    try:
        await handle_callback(state, code, redis, client)
    except OAuthStateError:
        return JSONResponse(status_code=400, content={"detail": "Invalid or expired state"})
    except Exception:
        logger.exception("Google OAuth callback failed")
        return JSONResponse(status_code=500, content={"detail": "Authorization failed"})
    return JSONResponse({"status": "authorized"})
