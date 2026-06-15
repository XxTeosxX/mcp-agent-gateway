import time
import uuid

from redis.exceptions import ResponseError

JOBS_STREAM = "jobs:drive_export"
GROUP = "exporters"
RESULT_TTL_SECONDS = 3600
OWNER_TTL_SECONDS = 3600

EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", "pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "txt": ("text/plain", "txt"),
}


async def ensure_group(redis) -> None:
    try:
        await redis.xgroup_create(JOBS_STREAM, GROUP, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def enqueue_export_job(redis, user_id: str, file_id: str, fmt: str) -> str:
    job_id = uuid.uuid4().hex
    await redis.set(f"job:owner:{job_id}", user_id, ex=OWNER_TTL_SECONDS)
    await redis.xadd(
        JOBS_STREAM,
        {
            "job_id": job_id,
            "user_id": user_id,
            "file_id": file_id,
            "format": fmt,
            "ts": str(time.time()),
        },
    )
    return job_id


async def job_owner(redis, job_id: str) -> str | None:
    return await redis.get(f"job:owner:{job_id}")


async def read_result(redis, job_id: str, timeout_ms: int) -> dict | None:
    resp = await redis.xread({f"results:{job_id}": "0"}, block=timeout_ms)
    if not resp:
        return None
    _stream, entries = resp[0]
    _entry_id, fields = entries[0]
    return fields
