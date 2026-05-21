import asyncio

import httpx
import pytest
import respx

from app.integrations.google.drive_client import DriveClient, drive_client


@pytest.fixture(autouse=True)
def setup_client():
    drive_client.init()
    yield
    asyncio.run(drive_client.close())


def test_get_raises_before_init():
    fresh = DriveClient()
    with pytest.raises(RuntimeError, match="not initialized"):
        fresh.get()


@pytest.mark.asyncio
@respx.mock
async def test_search_files_returns_list():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "abc123",
                        "name": "Proposal.pdf",
                        "mimeType": "application/pdf",
                        "webViewLink": "https://drive.google.com/file/abc123",
                        "modifiedTime": "2026-05-01T10:00:00Z",
                    }
                ]
            },
        )
    )

    result = await drive_client.search_files(token="fake-token", query="proposal", max_results=10, mime_type=None)

    assert len(result) == 1
    assert result[0]["id"] == "abc123"
    assert result[0]["name"] == "Proposal.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_search_files_with_mime_type_filter():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(return_value=httpx.Response(200, json={"files": []}))

    result = await drive_client.search_files(
        token="fake-token",
        query="report",
        max_results=5,
        mime_type="application/pdf",
    )

    assert result == []
    url_str = str(respx.calls[0].request.url)
    assert "application%2Fpdf" in url_str or "application/pdf" in url_str


@pytest.mark.asyncio
@respx.mock
async def test_get_file_content_native_doc_uses_export():
    file_id = "doc123"
    respx.get(f"https://www.googleapis.com/drive/v3/files/{file_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": file_id,
                "name": "My Doc",
                "mimeType": "application/vnd.google-apps.document",
            },
        )
    )
    respx.get(f"https://www.googleapis.com/drive/v3/files/{file_id}/export").mock(
        return_value=httpx.Response(200, text="Doc content here")
    )

    result = await drive_client.get_file_content(token="fake-token", file_id=file_id)

    assert result["content"] == "Doc content here"
    assert result["mime_type"] == "application/vnd.google-apps.document"


@pytest.mark.asyncio
@respx.mock
async def test_get_file_content_binary_uses_alt_media():
    file_id = "pdf123"
    respx.get(f"https://www.googleapis.com/drive/v3/files/{file_id}").mock(
        side_effect=[
            httpx.Response(200, json={"id": file_id, "name": "Report.pdf", "mimeType": "application/pdf"}),
            httpx.Response(200, text="PDF binary content"),
        ]
    )

    result = await drive_client.get_file_content(token="fake-token", file_id=file_id)

    assert result["content"] == "PDF binary content"


@pytest.mark.asyncio
@respx.mock
async def test_list_recent_returns_files():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "xyz",
                        "name": "Recent.docx",
                        "mimeType": "application/vnd.openxmlformats",
                        "webViewLink": "https://drive.google.com/file/xyz",
                        "modifiedTime": "2026-05-19T08:00:00Z",
                    }
                ]
            },
        )
    )

    result = await drive_client.list_recent(token="fake-token", days=7, max_results=20)

    assert len(result) == 1
    assert result[0]["name"] == "Recent.docx"


@pytest.mark.asyncio
@respx.mock
async def test_search_files_retries_on_500():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        side_effect=[
            httpx.Response(500, json={"error": "server error"}),
            httpx.Response(200, json={"files": []}),
        ]
    )

    result = await drive_client.search_files(token="fake-token", query="test", max_results=10, mime_type=None)

    assert result == []
    assert respx.calls.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_search_files_does_not_retry_on_401():
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await drive_client.search_files(token="bad-token", query="test", max_results=10, mime_type=None)

    assert exc_info.value.response.status_code == 401
    assert respx.calls.call_count == 1
