from urllib.parse import urlparse

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

import app.client_registry as client_registry
from app.client_metadata import (
    ClientMetadataFetchError,
    ClientMetadataValidationError,
    fetch_client_metadata,
)
from app.config import settings
from app.dcr import DcrRegistrationError, register_client

router = APIRouter(tags=["oauth"])

_redis_instance: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_instance


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _error_redirect(redirect_uri: str, error: str, description: str | None = None) -> RedirectResponse:
    params: dict = {"error": error}
    if description:
        params["error_description"] = description
    url = httpx.URL(redirect_uri).copy_with(params=params)
    return RedirectResponse(str(url), status_code=302)


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata() -> JSONResponse:
    return JSONResponse(
        content={
            "issuer": settings.GATEWAY_BASE_URL,
            "authorization_endpoint": f"{settings.GATEWAY_BASE_URL}/oauth/authorize",
            "token_endpoint": f"{settings.OAUTH_ISSUER_URL}/protocol/openid-connect/token",
            "jwks_uri": f"{settings.OAUTH_ISSUER_URL}/protocol/openid-connect/certs",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "client_credentials"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
            ],
        }
    )


@router.get("/oauth/authorize")
async def authorize(request: Request) -> RedirectResponse:
    params = dict(request.query_params)
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")

    if _is_url(client_id):
        redis = _get_redis()
        try:
            cached = await client_registry.get(client_id, redis=redis)
            if cached is None:
                metadata = await fetch_client_metadata(client_id, allow_http=settings.DEBUG)
                if redirect_uri not in metadata.redirect_uris:
                    return _error_redirect(redirect_uri, "invalid_request", "redirect_uri_not_in_metadata")
                dcr_result = await register_client(metadata)
                await client_registry.set(client_id, dcr_result, redis=redis)
                cached = dcr_result
            params["client_id"] = cached.client_id
        except ClientMetadataFetchError:
            return _error_redirect(redirect_uri, "invalid_client", "metadata_fetch_failed")
        except ClientMetadataValidationError as exc:
            description = "https_required" if "https_required" in str(exc) else "invalid_metadata"
            return _error_redirect(redirect_uri, "invalid_client", description)
        except DcrRegistrationError:
            return _error_redirect(redirect_uri, "server_error", "registration_failed")

    keycloak_authorize = f"{settings.OAUTH_ISSUER_URL}/protocol/openid-connect/auth"
    target = httpx.URL(keycloak_authorize).copy_with(params=params)
    return RedirectResponse(str(target), status_code=302)
