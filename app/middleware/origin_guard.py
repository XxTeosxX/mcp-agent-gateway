from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class OriginGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self._allowed = set(allowed_origins)

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/mcp"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._allowed:
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        return await call_next(request)
