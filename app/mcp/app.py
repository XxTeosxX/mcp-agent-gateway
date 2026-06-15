import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.integrations.google.drive_client import drive_client
from app.integrations.google.job_worker import JobWorker
from app.integrations.google.jobs import job_queue
from app.integrations.google.token_store import seed_shared_token_if_absent, token_store
from app.integrations.slack.slack_client import slack_client
from app.integrations.slack.token_store import seed_shared_slack_tokens_if_absent, slack_token_store
from app.mcp.server import create_session_manager
from app.shared.store import RedisStore
from app.shared.usage import usage_recorder


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
    await seed_shared_token_if_absent(token_store.get())
    slack_token_store.init(RedisStore(redis, "slack:token:"))
    await seed_shared_slack_tokens_if_absent(slack_token_store.get())
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
