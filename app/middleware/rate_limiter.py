import logging
import math
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("app.rate_limiter")

_RATE_LIMIT_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
    redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) * 1000)
end
local ttl = redis.call('PTTL', KEYS[1])
if n > tonumber(ARGV[1]) then
    return {0, ttl}
end
return {1, ttl}
"""

_script = None


def _get_script(redis):

    global _script
    if _script is None:
        _script = redis.register_script(_RATE_LIMIT_LUA)
    return _script


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


async def check_rate_limit(redis, key: str, limit: int, window: int) -> RateLimitResult:
    script = _get_script(redis)
    allowed, ttl_ms = await script(keys=[key], args=[limit, window], client=redis)
    retry_after = math.ceil(ttl_ms / 1000) if ttl_ms and ttl_ms > 0 else 0
    return RateLimitResult(allowed=bool(allowed), retry_after_seconds=retry_after)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)
        user = getattr(request.state, "user", None)
        if user is None:
            return await call_next(request)

        key = f"ratelimit:{user['id']}"
        try:
            result = await check_rate_limit(
                request.app.state.redis,
                key,
                settings.RATE_LIMIT_MAX_REQUESTS,
                settings.RATE_LIMIT_WINDOW_SECONDS,
            )
        except Exception:
            logger.warning("rate limiter unavailable, allowing request", exc_info=True)
            return await call_next(request)

        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(result.retry_after_seconds)},
            )
        return await call_next(request)
