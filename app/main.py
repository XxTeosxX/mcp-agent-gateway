from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.authorization.router import router as authorization_router
from app.config import settings
from app.gateway.health import router as health_router
from app.gateway.mcp import mcp_app, mcp_lifespan
from app.gateway.middleware.access_guard import AccessGuard
from app.gateway.middleware.rate_limiter import RateLimiterMiddleware
from app.gateway.middleware.request_logger import request_logging_middleware
from app.gateway.usage_router import router as usage_router
from app.identity.protected_resource import router as identity_router
from app.logging import configure_logging
from app.shared.http_client import HttpClient
from app.shared.redis import get_redis
from app.shared.store import RedisStore

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL is required")

    redis = await get_redis(settings.REDIS_URL)
    app.state.redis = redis
    app.state.oauth_state_store = RedisStore(redis, "state:")
    app.state.client_registry = RedisStore(redis, "client:")

    client = HttpClient()
    client.init()
    app.state.http_client = client

    async with mcp_lifespan(redis):
        yield

    await client.close()
    await redis.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Secure MCP gateway giving AI agents audited, least-privilege access to Google Drive and Slack over OAuth 2.1"
    ),
    lifespan=lifespan,
)

app.add_middleware(RateLimiterMiddleware)
app.add_middleware(AccessGuard)
app.middleware("http")(request_logging_middleware)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(authorization_router)
app.include_router(usage_router)

app.add_route("/mcp/", mcp_app)
