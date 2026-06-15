import asyncio
import logging
import os
import socket
import time
from pathlib import Path

from app.config import settings
from app.integrations.google.drive_client import drive_client as _drive_client
from app.integrations.google.jobs import (
    EXPORT_FORMATS,
    GROUP,
    JOBS_STREAM,
    RESULT_TTL_SECONDS,
    ensure_group,
)
from app.integrations.google.token_store import get_valid_google_token, token_store

logger = logging.getLogger("app.jobs")

_RECLAIM_IDLE_MS = 60_000
# Fallback throttle for the idle path. On real Redis, xreadgroup(block=...)
# already paces the loop; this only matters if BLOCK returns immediately
# (e.g. a backend that ignores BLOCK), preventing a 100% CPU busy-loop.
_IDLE_SLEEP_SECONDS = 0.1


class JobWorker:
    def __init__(self, redis, export_dir: str | None = None) -> None:
        self._redis = redis
        self._export_dir = export_dir or settings.EXPORT_DIR
        self._consumer = f"worker-{os.getenv('HOSTNAME') or socket.gethostname()}-{os.getpid()}"

    async def run(self) -> None:
        os.makedirs(self._export_dir, mode=0o700, exist_ok=True)
        os.chmod(self._export_dir, 0o700)
        await ensure_group(self._redis)
        while True:
            try:
                did_work = False
                for entry_id, fields in await self._reclaim():
                    await self._process(entry_id, fields)
                    did_work = True
                resp = await self._redis.xreadgroup(GROUP, self._consumer, {JOBS_STREAM: ">"}, count=1, block=5000)
                if resp:
                    for entry_id, fields in resp[0][1]:
                        await self._process(entry_id, fields)
                        did_work = True
                if not did_work:
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("job worker loop error", exc_info=True)
                await asyncio.sleep(1)

    async def _reclaim(self) -> list:
        try:
            _cursor, entries, _deleted = await self._redis.xautoclaim(
                JOBS_STREAM,
                GROUP,
                self._consumer,
                min_idle_time=_RECLAIM_IDLE_MS,
                start_id="0-0",
                count=10,
            )
            return entries
        except Exception:
            logger.warning("xautoclaim failed", exc_info=True)
            return []

    async def _process(self, entry_id, fields) -> None:
        job_id = fields["job_id"]
        try:
            export_mime, ext = EXPORT_FORMATS[fields["format"]]
            token = await get_valid_google_token(fields["user_id"], _drive_client.get(), token_store.get())
            data = await _drive_client.export_file(token, fields["file_id"], export_mime)
            path = os.path.join(self._export_dir, f"{job_id}.{ext}")
            await asyncio.to_thread(Path(path).write_bytes, data)
            os.chmod(path, 0o600)
            await self._publish(
                job_id,
                {
                    "status": "completed",
                    "path": path,
                    "size_bytes": str(len(data)),
                    "mime": export_mime,
                    "user_id": fields["user_id"],
                    "ts": str(time.time()),
                },
            )
        except Exception as exc:
            logger.warning("export job %s failed", job_id, exc_info=True)
            await self._publish(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc),
                    "user_id": fields["user_id"],
                    "ts": str(time.time()),
                },
            )
        finally:
            await self._redis.xack(JOBS_STREAM, GROUP, entry_id)

    async def _publish(self, job_id: str, record: dict) -> None:
        key = f"results:{job_id}"
        await self._redis.xadd(key, record)
        await self._redis.expire(key, RESULT_TTL_SECONDS)
        await self._redis.expire(f"job:owner:{job_id}", RESULT_TTL_SECONDS)
