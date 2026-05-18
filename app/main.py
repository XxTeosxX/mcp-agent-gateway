from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.logging import configure_logging
from app.middlewares import AuthMiddleware, request_logging_middleware
from app.routers import auth, health, oauth
from app.routers.mcp import mcp_app, mcp_lifespan

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

app.add_middleware(AuthMiddleware)
app.middleware("http")(request_logging_middleware)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(oauth.router)

app.add_route("/mcp/", mcp_app)
