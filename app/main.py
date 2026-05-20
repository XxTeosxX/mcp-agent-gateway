from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.authorization.router import router as authorization_router
from app.config import settings
from app.gateway.health import router as health_router
from app.gateway.mcp import mcp_app, mcp_lifespan
from app.gateway.middleware.access_guard import AccessGuard
from app.gateway.middleware.request_logger import request_logging_middleware
from app.identity.protected_resource import router as identity_router
from app.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_lifespan():
        yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Secure MCP gateway giving AI agents audited, least-privilege access to Google Drive and Slack over OAuth 2.1"
    ),
    lifespan=lifespan,
)

app.add_middleware(AccessGuard)
app.middleware("http")(request_logging_middleware)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(authorization_router)

app.add_route("/mcp/", mcp_app)
