import json
import logging
from collections.abc import Awaitable, Callable

from mcp import types
from pydantic import BaseModel, Field, ValidationError

from app.gateway.context import current_user_id
from app.gateway.jobs import (
    EXPORT_FORMATS,
    enqueue_export_job,
    job_owner,
    job_queue,
    read_result,
)
from app.gateway.usage import track_usage

logger = logging.getLogger(__name__)


class ExportInput(BaseModel):
    file_id: str
    format: str = Field(default="pdf")


class WaitInput(BaseModel):
    job_id: str
    timeout_seconds: int = Field(default=30, ge=1, le=120)


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=message)],
    )


def _ok(data: dict) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(data))])


@track_usage("drive-export-large-file")
async def handle_drive_export_large_file(arguments: dict) -> types.CallToolResult:
    try:
        args = ExportInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    if args.format not in EXPORT_FORMATS:
        return _error(f"Unsupported format '{args.format}'. Supported: {', '.join(EXPORT_FORMATS)}")

    try:
        job_id = await enqueue_export_job(job_queue.get(), current_user_id.get(), args.file_id, args.format)
    except Exception:
        logger.warning("failed to enqueue export job", exc_info=True)
        return _error("Could not enqueue export job — try again later.")

    return _ok({"job_id": job_id, "status": "queued"})


@track_usage("wait-for-job")
async def handle_wait_for_job(arguments: dict) -> types.CallToolResult:
    try:
        args = WaitInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    redis = job_queue.get()
    owner = await job_owner(redis, args.job_id)
    if owner is None or owner != current_user_id.get():
        return _error("job not found")

    result = await read_result(redis, args.job_id, args.timeout_seconds * 1000)
    if result is None:
        return _ok({"job_id": args.job_id, "status": "pending"})
    return _ok(result)


JOB_TOOLS: list[types.Tool] = [
    types.Tool(
        name="drive-export-large-file",
        description=(
            "Start an asynchronous export of a Google Drive file to pdf, docx, or "
            "txt. Returns a job_id immediately; poll with wait-for-job."
        ),
        inputSchema={
            "type": "object",
            "required": ["file_id"],
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID to export"},
                "format": {"type": "string", "enum": ["pdf", "docx", "txt"], "default": "pdf"},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=False),
    ),
    types.Tool(
        name="wait-for-job",
        description=(
            "Block until an export job finishes (or timeout). Returns the job "
            "result, or status 'pending' on timeout. Only the user who created the "
            "job may read it."
        ),
        inputSchema={
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "job_id": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 30, "minimum": 1, "maximum": 120},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
]

JOB_REGISTRY: dict[str, Callable[[dict], Awaitable[types.CallToolResult]]] = {
    "drive-export-large-file": handle_drive_export_large_file,
    "wait-for-job": handle_wait_for_job,
}
