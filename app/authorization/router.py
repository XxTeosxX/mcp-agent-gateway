import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.identity.client_registration import repository as client_repository
from app.identity.client_registration.models import (
    ClientMetadataFetchError,
    ClientMetadataValidationError,
    fetch_client_metadata,
)
from app.identity.client_registration.registrar import DcrRegistrationError, enroll_mcp_client
from app.integrations.google.oauth_flow import OAuthStateError, build_authorization_url, handle_callback
from app.shared.http_client import get_http_client
from app.shared.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["authorization"])


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
        redis = get_redis()
        try:
            cached = await client_repository.get(client_id, redis=redis)
            if cached is None:
                metadata = await fetch_client_metadata(client_id, allow_http=settings.DEBUG)
                if redirect_uri not in metadata.redirect_uris:
                    return _error_redirect(redirect_uri, "invalid_request", "redirect_uri_not_in_metadata")
                registered = await enroll_mcp_client(metadata)
                await client_repository.set(client_id, registered, redis=redis)
                cached = registered
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


@router.post("/auth/google/initiate")
async def google_initiate(request: Request) -> JSONResponse:
    user_id: str = request.state.user["id"]
    authorization_url, state = await build_authorization_url(user_id, get_redis())
    return JSONResponse({"authorization_url": authorization_url, "state": state})


@router.get("/auth/google/callback")
async def google_callback(state: str, code: str) -> JSONResponse:
    try:
        await handle_callback(state, code, get_redis(), get_http_client())
    except OAuthStateError:
        return JSONResponse(status_code=400, content={"detail": "Invalid or expired state"})
    except Exception:
        logger.exception("Google OAuth callback failed")
        return JSONResponse(status_code=500, content={"detail": "Authorization failed"})
    return JSONResponse({"status": "authorized"})
