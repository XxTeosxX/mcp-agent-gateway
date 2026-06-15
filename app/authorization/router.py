from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.authorization.pkce import validate_pkce_params
from app.config import settings
from app.identity.client_registration import repository as client_repository
from app.identity.client_registration.models import (
    ClientMetadataFetchError,
    ClientMetadataValidationError,
    fetch_client_metadata,
)
from app.identity.client_registration.registrar import DcrRegistrationError, enroll_mcp_client
from app.shared.dependencies import get_client_registry
from app.shared.store import Store

router = APIRouter(tags=["authorization"])


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _error_response(error: str, description: str | None = None) -> JSONResponse:
    """Return an OAuth error locally.

    We deliberately do NOT 302-redirect to the request's redirect_uri on these errors:
    at this point the redirect_uri has either failed validation or not been validated
    yet, and bouncing the user there would be an open redirect.
    """
    body: dict = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(status_code=400, content=body)


def _authorize_params_valid(params: dict) -> tuple[bool, str]:
    """OAuth 2.1 authorization request validation.

    Returns (ok, error_description). On failure the caller must return
    invalid_request without redirecting.
    """
    if not params.get("client_id"):
        return False, "client_id is required"
    if params.get("response_type") != "code":
        return False, "response_type must be code"
    if not params.get("redirect_uri"):
        return False, "redirect_uri is required"
    if not params.get("state"):
        return False, "state is required"
    try:
        validate_pkce_params(params.get("code_challenge"), params.get("code_challenge_method"))
    except ValueError as exc:
        return False, str(exc)
    return True, ""


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


@router.get("/oauth/authorize", response_model=None)
async def authorize(
    request: Request,
    registry: Store = Depends(get_client_registry),
) -> RedirectResponse | JSONResponse:
    params = dict(request.query_params)
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")

    # OAuth 2.1 requires PKCE, state, and a redirect_uri before any redirect.
    ok, description = _authorize_params_valid(params)
    if not ok:
        return _error_response("invalid_request", description)

    if _is_url(client_id):
        try:
            cached = await client_repository.get(client_id, registry)
            if cached is None:
                metadata = await fetch_client_metadata(client_id, allow_http=settings.DEBUG)
                # Validate redirect_uri against the client's registered set BEFORE the
                # user could ever be redirected there — never bounce to an unvalidated URI.
                if redirect_uri not in metadata.redirect_uris:
                    return _error_response("invalid_request", "redirect_uri_not_in_metadata")
                registered = await enroll_mcp_client(metadata)
                await client_repository.set(client_id, registered, registry)
                cached = registered
            elif redirect_uri not in cached.redirect_uris:
                # Cached DCR registrations must still enforce the redirect_uri allowlist.
                return _error_response("invalid_request", "redirect_uri_not_in_metadata")
            params["client_id"] = cached.client_id
        except ClientMetadataFetchError:
            return _error_response("invalid_client", "metadata_fetch_failed")
        except ClientMetadataValidationError as exc:
            description = "https_required" if "https_required" in str(exc) else "invalid_metadata"
            return _error_response("invalid_client", description)
        except DcrRegistrationError:
            return _error_response("server_error", "registration_failed")

    keycloak_authorize = f"{settings.OAUTH_ISSUER_URL}/protocol/openid-connect/auth"
    target = httpx.URL(keycloak_authorize).copy_with(params=params)
    return RedirectResponse(str(target), status_code=302)
