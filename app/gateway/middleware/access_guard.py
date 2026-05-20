from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.identity.token_validator import token_validator

_AUTH_BYPASS_EXACT = frozenset(
    {
        "/openapi.json",
        "/oauth/authorize",
        "/auth/google/callback",
    }
)

_AUTH_BYPASS_PREFIXES = (
    "/health",
    "/.well-known",
    "/docs",
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
            return self._unauthorized(request)

        token = auth_header[7:]
        try:
            claims = token_validator.validate(token)
        except ValueError:
            return self._unauthorized(request)

        request.state.user = {
            "id": claims["sub"],
            "scopes": claims.get("scope", "").split(),
            "token": claims,
        }
        return await call_next(request)

    @staticmethod
    def _unauthorized(request: Request) -> JSONResponse:
        resource_base = settings.OAUTH_EXPECTED_AUDIENCE.rstrip("/").rsplit("/", 1)[0]
        well_known = f"{resource_base}/.well-known/oauth-protected-resource"
        scopes = "mcp:tools:read mcp:tools:write"
        www_auth = f'Bearer resource_metadata="{well_known}", scope="{scopes}"'
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": www_auth},
        )
