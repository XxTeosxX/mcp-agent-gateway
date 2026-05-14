from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.logging import configure_logging
from app.middlewares import request_logging_middleware
from app.routers import health
from app.routers.mcp import handle_streamable_http, mcp_lifespan

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

app.middleware("http")(request_logging_middleware)
app.include_router(health.router)

app.mount("/mcp", handle_streamable_http, name="mcp")
