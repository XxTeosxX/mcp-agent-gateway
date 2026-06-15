import asyncio
from contextlib import asynccontextmanager, suppress

from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.usage_router import router as usage_router
from app.api.webhooks_router import router as webhooks_router
from app.authorization.router import router as authorization_router
from app.config import settings
from app.identity.protected_resource import router as identity_router
from app.integrations.google.drive_client import DriveClient
from app.integrations.google.job_worker import JobWorker
from app.integrations.google.token_store import seed_shared_token_if_absent
from app.integrations.slack.slack_client import SlackClient
from app.integrations.slack.token_store import seed_shared_slack_tokens_if_absent
from app.logging import configure_logging
from app.mcp.app import mcp_app, mcp_lifespan
from app.mcp.health import router as health_router
from app.middleware.access_guard import AccessGuard
from app.middleware.origin_guard import OriginGuardMiddleware
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.request_logger import request_logging_middleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.shared.http_client import HttpClient
from app.shared.redis import create_redis
from app.shared.store import RedisStore

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL is required")

    redis = await create_redis(settings.REDIS_URL)

    http_client: HttpClient | None = None
    drive_client: DriveClient | None = None
    slack_client: SlackClient | None = None
    jobs_redis = None
    worker_task: asyncio.Task | None = None

    try:
        # --- route-facing deps → app.state ---
        app.state.redis = redis
        http_client = HttpClient(timeout=10.0)
        app.state.http_client = http_client
        app.state.oauth_state_store = RedisStore(redis, "state:")
        app.state.client_registry = RedisStore(redis, "client:")
        app.state.slack_signing_secret = settings.SLACK_SIGNING_SECRET

        # --- MCP-only deps → locals ---
        drive_client = DriveClient(
            timeout=settings.GOOGLE_DRIVE_TIMEOUT,
            max_connections=settings.GOOGLE_DRIVE_MAX_CONNECTIONS,
            max_keepalive=settings.GOOGLE_DRIVE_MAX_KEEPALIVE,
            max_retries=settings.GOOGLE_DRIVE_MAX_RETRIES,
        )
        slack_client = SlackClient(timeout=settings.SLACK_TIMEOUT, max_retries=settings.SLACK_MAX_RETRIES)
        google_token_store = RedisStore(redis, "token:")
        slack_token_store = RedisStore(redis, "slack:token:")
        google_fernet = Fernet(settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())
        slack_fernet = Fernet(settings.SLACK_TOKEN_ENCRYPTION_KEY.encode())

        await seed_shared_token_if_absent(google_token_store, google_fernet, settings.GOOGLE_SHARED_REFRESH_TOKEN)
        await seed_shared_slack_tokens_if_absent(
            slack_token_store, slack_fernet, settings.SLACK_SHARED_BOT_TOKEN, settings.SLACK_SHARED_USER_TOKEN
        )

        jobs_redis = await create_redis(settings.REDIS_URL, socket_timeout=None)
        worker = JobWorker(
            redis=jobs_redis,
            drive_client=drive_client,
            token_store=google_token_store,
            fernet=google_fernet,
            http_client=http_client,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            export_dir=settings.EXPORT_DIR,
        )
        worker_task = asyncio.create_task(worker.run())

        async with mcp_lifespan(
            redis=redis,
            jobs_redis=jobs_redis,
            http_client=http_client,
            drive_client=drive_client,
            slack_client=slack_client,
            google_token_store=google_token_store,
            slack_token_store=slack_token_store,
            google_fernet=google_fernet,
            slack_fernet=slack_fernet,
            google_client_id=settings.GOOGLE_CLIENT_ID,
            google_client_secret=settings.GOOGLE_CLIENT_SECRET,
        ):
            yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        if jobs_redis is not None:
            await jobs_redis.aclose()
        if drive_client is not None:
            await drive_client.close()
        if slack_client is not None:
            await slack_client.close()
        if http_client is not None:
            await http_client.close()
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
app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.ALLOWED_ORIGINS)
app.middleware("http")(request_logging_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(authorization_router)
app.include_router(usage_router)
app.include_router(webhooks_router)

app.add_route("/mcp/", mcp_app)
