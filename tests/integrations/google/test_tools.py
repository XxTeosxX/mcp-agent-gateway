import json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.integrations.google import tools as drive_tools
from app.integrations.google.drive_client import DriveClient
from app.integrations.google.tools import DriveSearchInput
from app.shared.context import current_user_id
from app.shared.http_client import HttpClient
from app.shared.store import InMemoryStore


@pytest.fixture
def fernet():
    return Fernet(Fernet.generate_key())


@pytest.fixture
async def deps(fernet):
    dc = DriveClient(timeout=10.0, max_connections=10, max_keepalive=5, max_retries=3)
    http = HttpClient()
    store = InMemoryStore()
    yield dict(
        drive_client=dc,
        token_store=store,
        fernet=fernet,
        http_client=http,
        client_id="cid",
        client_secret="secret",
    )
    await dc.close()
    await http.close()


@pytest.fixture
async def stored_token(deps):
    enc = deps["fernet"].encrypt(b"fake-refresh-token").decode()
    await deps["token_store"].set(
        "google:shared",
        json.dumps(
            {
                "access_token": "valid-access-token",
                "refresh_token_enc": enc,
                "expires_at": time.time() + 3600,
            }
        ),
    )


@pytest.mark.asyncio
@respx.mock
async def test_drive_search_files_returns_structured_result(deps, stored_token):
    current_user_id.set("user-123")

    route = respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "f1",
                        "name": "Proposal.pdf",
                        "mimeType": "application/pdf",
                        "webViewLink": "https://drive.google.com/f1",
                        "modifiedTime": "2026-05-01T10:00:00Z",
                    }
                ]
            },
        )
    )

    result = await drive_tools.handle_drive_search_files({"full_text": "proposal", "max_results": 10}, **deps)

    assert result.isError is False
    assert result.structuredContent == {
        "files": [
            {
                "file_id": "f1",
                "name": "Proposal.pdf",
                "mime_type": "application/pdf",
                "web_view_link": "https://drive.google.com/f1",
                "modified_time": "2026-05-01T10:00:00Z",
            }
        ]
    }
    assert json.loads(result.content[0].text) == result.structuredContent
    assert "fullText" in str(route.calls[0].request.url) or "fullText+contains" in str(route.calls[0].request.url)


@pytest.mark.asyncio
async def test_drive_search_files_no_token_returns_error(deps):
    current_user_id.set("user-no-token")

    result = await drive_tools.handle_drive_search_files({"full_text": "anything"}, **deps)

    assert result.isError is True
    assert "authorize" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_drive_search_files_no_filter_returns_error(deps):
    current_user_id.set("user-123")
    result = await drive_tools.handle_drive_search_files({}, **deps)
    assert result.isError is True
    assert "at least one search filter" in result.content[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_drive_search_files_http_error_returns_clean_error(deps, stored_token):
    current_user_id.set("user-123")
    respx.get("https://www.googleapis.com/drive/v3/files").mock(return_value=httpx.Response(400, json={"error": "bad"}))

    result = await drive_tools.handle_drive_search_files({"full_text": "x"}, **deps)

    assert result.isError is True
    text = result.content[0].text.lower()
    assert "drive search failed" in text
    assert "traceback" not in text


def test_drive_tools_list_has_three_tools():
    assert len(drive_tools.DRIVE_TOOLS) == 3
    names = {t.name for t in drive_tools.DRIVE_TOOLS}
    assert names == {"drive-search-files", "drive-get-file-content", "drive-list-recent"}


def test_build_drive_registry_wraps_with_usage(deps):
    registry = drive_tools.build_drive_registry(redis=None, **deps)
    assert set(registry) == {"drive-search-files", "drive-get-file-content", "drive-list-recent"}
    for handler in registry.values():
        assert hasattr(handler, "__wrapped__")


def test_input_accepts_single_filter():
    model = DriveSearchInput(full_text="proposals")
    assert model.full_text == "proposals"
    assert model.include_trashed is False
    assert model.max_results == 10


def test_input_rejects_no_filter():
    with pytest.raises(ValidationError, match="at least one search filter"):
        DriveSearchInput()


def test_input_include_trashed_alone_is_not_a_filter():
    with pytest.raises(ValidationError, match="at least one search filter"):
        DriveSearchInput(include_trashed=True)


def test_input_max_results_alone_is_not_a_filter():
    with pytest.raises(ValidationError, match="at least one search filter"):
        DriveSearchInput(max_results=50)


@pytest.mark.asyncio
@respx.mock
async def test_drive_search_files_network_error_returns_clean_error(deps, stored_token):
    current_user_id.set("user-123")
    respx.get("https://www.googleapis.com/drive/v3/files").mock(side_effect=httpx.ConnectError("boom"))

    result = await drive_tools.handle_drive_search_files({"full_text": "x"}, **deps)

    assert result.isError is True
    text = result.content[0].text.lower()
    assert "drive search failed" in text
    assert "network" in text
    assert "boom" not in text
    assert "traceback" not in text


def _drive_search_tool():
    return next(t for t in drive_tools.DRIVE_TOOLS if t.name == "drive-search-files")


def test_drive_search_input_schema_is_structured():
    tool = _drive_search_tool()
    props = tool.inputSchema["properties"]
    assert set(props) >= {
        "name_contains",
        "full_text",
        "mime_type",
        "in_folder",
        "modified_after",
        "include_trashed",
        "max_results",
    }
    assert "query" not in props
    assert tool.inputSchema.get("required", []) == []


def test_drive_search_declares_output_schema():
    tool = _drive_search_tool()
    assert tool.outputSchema is not None
    files = tool.outputSchema["properties"]["files"]
    assert files["type"] == "array"
    assert set(files["items"]["properties"]) == {
        "file_id",
        "name",
        "mime_type",
        "web_view_link",
        "modified_time",
    }


def test_drive_search_description_is_honest():
    tool = _drive_search_tool()
    assert "structured filters" in tool.description.lower()
    assert "query syntax" in tool.description.lower()
