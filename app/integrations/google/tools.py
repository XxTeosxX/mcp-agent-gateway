import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date

import httpx
from mcp import types
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.integrations.google.drive_client import drive_client as _drive_client
from app.integrations.google.drive_query import build_drive_query
from app.integrations.google.token_store import (
    _GOOGLE_SHARED_USER,
    OAuthTokenNotFoundError,
    get_valid_google_token,
    token_store,
)
from app.shared.usage import track_usage

logger = logging.getLogger(__name__)


class DriveSearchInput(BaseModel):
    name_contains: str | None = None
    full_text: str | None = None
    mime_type: str | None = None
    in_folder: str | None = None
    modified_after: date | None = None
    include_trashed: bool = False
    max_results: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _require_filter(self) -> "DriveSearchInput":
        if not any([self.name_contains, self.full_text, self.mime_type, self.in_folder, self.modified_after]):
            raise ValueError("provide at least one search filter")
        return self


class DriveGetFileInput(BaseModel):
    file_id: str


class DriveListRecentInput(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    max_results: int = Field(default=20, ge=1, le=100)


class DriveFile(BaseModel):
    file_id: str
    name: str
    mime_type: str
    web_view_link: str
    modified_time: str


class DriveFileContent(BaseModel):
    file_id: str
    name: str
    content: str
    mime_type: str


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=message)],
    )


def _ok(data) -> types.CallToolResult:
    text = json.dumps(data) if not isinstance(data, str) else data
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _ok_structured(files: list[dict]) -> types.CallToolResult:
    payload = {"files": files}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
    )


def _to_drive_file(f: dict) -> dict:
    return DriveFile(
        file_id=f["id"],
        name=f["name"],
        mime_type=f["mimeType"],
        web_view_link=f.get("webViewLink", ""),
        modified_time=f.get("modifiedTime", ""),
    ).model_dump()


# All gateway-authenticated users share one upstream Google token
# (_GOOGLE_SHARED_USER), provisioned via GOOGLE_SHARED_REFRESH_TOKEN. The
# downstream user's identity is NEVER forwarded to Google (Confused Deputy).
_NOT_AUTHORIZED = (
    "Google Drive is not authorized. Provision a shared refresh token via GOOGLE_SHARED_REFRESH_TOKEN (see README)."
)


async def _get_drive_token() -> str | types.CallToolResult:
    try:
        return await get_valid_google_token(_GOOGLE_SHARED_USER, _drive_client.get(), token_store.get())
    except OAuthTokenNotFoundError:
        return _error(_NOT_AUTHORIZED)


@track_usage("drive-search-files")
async def handle_drive_search_files(arguments: dict) -> types.CallToolResult:
    try:
        args = DriveSearchInput(**arguments)
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = ".".join(str(part) for part in err["loc"]) or "input"
        return _error(f"Invalid input: {loc} — {err['msg']}")

    token = await _get_drive_token()
    if isinstance(token, types.CallToolResult):
        return token

    q = build_drive_query(
        name_contains=args.name_contains,
        full_text=args.full_text,
        mime_type=args.mime_type,
        in_folder=args.in_folder,
        modified_after=args.modified_after,
        include_trashed=args.include_trashed,
    )
    try:
        files = await _drive_client.search_files(token, q, args.max_results)
    except httpx.HTTPStatusError as exc:
        return _error(f"Drive search failed: {exc.response.status_code}")
    except httpx.RequestError:
        return _error("Drive search failed: network error")
    return _ok_structured([_to_drive_file(f) for f in files])


@track_usage("drive-get-file-content")
async def handle_drive_get_file_content(arguments: dict) -> types.CallToolResult:
    try:
        args = DriveGetFileInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_drive_token()
    if isinstance(token, types.CallToolResult):
        return token

    file_data = await _drive_client.get_file_content(token, args.file_id)
    return _ok(DriveFileContent(**file_data).model_dump())


@track_usage("drive-list-recent")
async def handle_drive_list_recent(arguments: dict) -> types.CallToolResult:
    try:
        args = DriveListRecentInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_drive_token()
    if isinstance(token, types.CallToolResult):
        return token

    files = await _drive_client.list_recent(token, args.days, args.max_results)
    return _ok([_to_drive_file(f) for f in files])


DRIVE_REQUIRED_SCOPE = "mcp:google:read"

DRIVE_TOOLS: list[types.Tool] = [
    types.Tool(
        name="drive-search-files",
        description=(
            "Search the shared Google Drive using structured filters (name, full text, MIME type, "
            "parent folder, modified-after date). At least one filter is required. The gateway "
            "composes the Drive query safely — callers never write Drive query syntax."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name_contains": {"type": "string", "description": "Match files whose name contains this text"},
                "full_text": {"type": "string", "description": "Full-text search within file contents and metadata"},
                "mime_type": {"type": "string", "description": "Filter by MIME type (e.g. 'application/pdf')"},
                "in_folder": {"type": "string", "description": "Restrict to children of this Drive folder ID"},
                "modified_after": {
                    "type": "string",
                    "format": "date",
                    "description": "Only files modified after this date (YYYY-MM-DD)",
                },
                "include_trashed": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            },
        },
        outputSchema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string"},
                            "name": {"type": "string"},
                            "mime_type": {"type": "string"},
                            "web_view_link": {"type": "string"},
                            "modified_time": {"type": "string"},
                        },
                    },
                }
            },
            "required": ["files"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="drive-get-file-content",
        description="Read the content of a file from Google Drive. Native Google Docs are exported as plain text.",
        inputSchema={
            "type": "object",
            "required": ["file_id"],
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID"},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="drive-list-recent",
        description="List files modified in the last N days from the user's Google Drive.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 90},
                "max_results": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
]

DRIVE_REGISTRY: dict[str, Callable[[dict], Awaitable[types.CallToolResult]]] = {
    "drive-search-files": handle_drive_search_files,
    "drive-get-file-content": handle_drive_get_file_content,
    "drive-list-recent": handle_drive_list_recent,
}
