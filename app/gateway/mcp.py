import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.gateway.job_worker import JobWorker
from app.gateway.jobs import job_queue
from app.gateway.server import create_session_manager
from app.gateway.usage import usage_recorder
from app.integrations.google.drive_client import drive_client
from app.integrations.slack.slack_client import slack_client
from app.shared.store import RedisStore, slack_token_store, token_store


class MCPApp:
    def __init__(self) -> None:
        self._manager: StreamableHTTPSessionManager | None = None

    def set_manager(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._manager is None:
            raise RuntimeError("mcp_app: session manager not initialized")
        await self._manager.handle_request(scope, receive, send)


mcp_app = MCPApp()


@asynccontextmanager
async def mcp_lifespan(redis) -> AsyncIterator[None]:
    manager = create_session_manager()
    mcp_app.set_manager(manager)
    drive_client.init()
    slack_client.init()
    token_store.init(RedisStore(redis, "token:"))
    slack_token_store.init(RedisStore(redis, "slack:token:"))
    usage_recorder.init(redis)
    job_queue.init(redis)
    worker_task = asyncio.create_task(JobWorker(redis).run())
    async with manager.run():
        yield
    worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await worker_task
    await drive_client.close()
    await slack_client.close()
