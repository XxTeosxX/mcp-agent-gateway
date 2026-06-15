import json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import settings
from app.integrations.google import tools as drive_tools
from app.integrations.google.drive_client import drive_client
from app.integrations.google.token_store import token_store
from app.integrations.google.tools import DriveSearchInput
from app.shared.context import current_user_id
from app.shared.store import InMemoryStore


@pytest.fixture(autouse=True)
def setup_drive_client():
    drive_client.init()
    yield
    import asyncio

    asyncio.run(drive_client.close())


@pytest.fixture(autouse=True)
def _init_token_store():
    token_store.init(InMemoryStore())
    yield


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    return key


@pytest.fixture
async def stored_token(encryption_key):
    key = settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode()
    enc = Fernet(key).encrypt(b"fake-refresh-token").decode()
    await token_store.get().set(
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
async def test_drive_search_files_returns_structured_result(stored_token, encryption_key):
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

    result = await drive_tools.handle_drive_search_files({"full_text": "proposal", "max_results": 10})

    assert result.isError is False
    # structured output
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
    # text mirror still present
    assert json.loads(result.content[0].text) == result.structuredContent
    # server composed the q from structured filters
    assert "fullText+contains" in str(route.calls[0].request.url) or "fullText contains" in str(
        route.calls[0].request.url
    )


@pytest.mark.asyncio
async def test_drive_search_files_no_token_returns_error():
    current_user_id.set("user-no-token")

    result = await drive_tools.handle_drive_search_files({"full_text": "anything"})

    assert result.isError is True
    assert "authorize" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_drive_search_files_no_filter_returns_error():
    current_user_id.set("user-123")
    result = await drive_tools.handle_drive_search_files({})
    assert result.isError is True
    assert "at least one search filter" in result.content[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_drive_search_files_http_error_returns_clean_error(stored_token, encryption_key):
    current_user_id.set("user-123")
    respx.get("https://www.googleapis.com/drive/v3/files").mock(return_value=httpx.Response(400, json={"error": "bad"}))

    result = await drive_tools.handle_drive_search_files({"full_text": "x"})

    assert result.isError is True
    text = result.content[0].text.lower()
    assert "drive search failed" in text
    assert "traceback" not in text


def test_drive_tools_list_has_three_tools():
    assert len(drive_tools.DRIVE_TOOLS) == 3
    names = {t.name for t in drive_tools.DRIVE_TOOLS}
    assert names == {"drive-search-files", "drive-get-file-content", "drive-list-recent"}


def test_drive_registry_has_three_handlers():
    assert set(drive_tools.DRIVE_REGISTRY.keys()) == {
        "drive-search-files",
        "drive-get-file-content",
        "drive-list-recent",
    }


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
async def test_drive_search_files_network_error_returns_clean_error(stored_token, encryption_key):
    current_user_id.set("user-123")
    respx.get("https://www.googleapis.com/drive/v3/files").mock(side_effect=httpx.ConnectError("boom"))

    result = await drive_tools.handle_drive_search_files({"full_text": "x"})

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
