import logging
import time
import uuid

from fastapi import Request
from opentelemetry.trace import get_current_span
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth import token_validator
from app.config import settings

logger = logging.getLogger("app.request")

_AUTH_BYPASS_PREFIXES = (
    "/health",
    "/.well-known",
    "/docs",
    "/openapi.json",
    "/oauth/authorize",
    "/auth/google/callback",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path == p or path.startswith(p) for p in _AUTH_BYPASS_PREFIXES):
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


async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    extra = {
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
        "request_id": request_id,
    }
    span_context = get_current_span().get_span_context()
    if span_context.is_valid:
        extra["trace_id"] = format(span_context.trace_id, "032x")
        extra["span_id"] = format(span_context.span_id, "016x")
    response.headers["x-request-id"] = request_id
    logger.info("request", extra=extra)
    return response
