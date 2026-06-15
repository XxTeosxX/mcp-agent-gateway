from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.identity.token_validator import token_validator
from app.shared.context import current_user_id, current_user_scopes

_SCOPES = "mcp:google:read mcp:slack:read mcp:admin:read"

# Keycloak client `mcp-gateway` roles → gateway scopes. The role is the source
# of truth; downstream code reads only scopes.
_CLIENT_ID = "mcp-gateway"
_ROLE_SCOPE_MAP = {
    "drive-user": "mcp:google:read",
    "slack-user": "mcp:slack:read",
    "admin-user": "mcp:admin:read",
}

_AUTH_BYPASS_EXACT = frozenset(
    {
        "/openapi.json",
        "/oauth/authorize",
    }
)

_AUTH_BYPASS_PREFIXES = (
    "/health",
    "/.well-known",
    "/docs",
    "/webhooks",
)


def _is_bypass_path(path: str) -> bool:
    return path in _AUTH_BYPASS_EXACT or any(path == p or path.startswith(p + "/") for p in _AUTH_BYPASS_PREFIXES)


class AccessGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _is_bypass_path(path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return self._unauthorized()

        token = auth_header[7:]
        try:
            claims = token_validator.validate(token)
        except ValueError:
            return self._unauthorized()

        scopes = set(claims.get("scope", "").split())
        client_roles = claims.get("resource_access", {}).get(_CLIENT_ID, {}).get("roles", [])
        scopes |= {_ROLE_SCOPE_MAP[r] for r in client_roles if r in _ROLE_SCOPE_MAP}

        request.state.user = {
            "id": claims["sub"],
            "scopes": sorted(scopes),
            "token": claims,
        }
        current_user_id.set(claims["sub"])
        current_user_scopes.set(frozenset(scopes))
        return await call_next(request)

    @staticmethod
    def _unauthorized() -> JSONResponse:
        resource_base = settings.OAUTH_EXPECTED_AUDIENCE.rstrip("/").rsplit("/", 1)[0]
        well_known = f"{resource_base}/.well-known/oauth-protected-resource"
        www_auth = f'Bearer resource_metadata="{well_known}", scope="{_SCOPES}"'
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": www_auth},
        )
