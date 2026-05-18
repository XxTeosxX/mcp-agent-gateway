import httpx
import pytest

from app.client_metadata import (
    ClientMetadata,
    ClientMetadataFetchError,
    ClientMetadataValidationError,
    fetch_client_metadata,
)

_VALID = {
    "redirect_uris": ["https://myapp.com/callback"],
    "client_name": "My MCP App",
    "scope": "mcp:tools:read mcp:tools:write",
}


def _transport(status: int, body: dict, content_type: str = "application/json") -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


class TestFetchClientMetadata:
    async def test_returns_client_metadata_on_success(self):
        result = await fetch_client_metadata(
            "https://myapp.com/meta.json", allow_http=False, _transport=_transport(200, _VALID)
        )
        assert isinstance(result, ClientMetadata)
        assert result.redirect_uris == ["https://myapp.com/callback"]
        assert result.client_name == "My MCP App"

    async def test_optional_fields_are_none_when_absent(self):
        result = await fetch_client_metadata(
            "https://myapp.com/meta.json", allow_http=False, _transport=_transport(200, _VALID)
        )
        assert result.scope == "mcp:tools:read mcp:tools:write"
        assert result.grant_types is None

    async def test_raises_fetch_error_on_404(self):
        with pytest.raises(ClientMetadataFetchError):
            await fetch_client_metadata("https://myapp.com/meta.json", allow_http=False, _transport=_transport(404, {}))

    async def test_raises_fetch_error_on_timeout(self):
        def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        with pytest.raises(ClientMetadataFetchError, match="Timeout"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=httpx.MockTransport(timeout_handler),
            )

    async def test_raises_validation_error_on_wrong_content_type(self):
        with pytest.raises(ClientMetadataValidationError, match="application/json"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, _VALID, content_type="text/html"),
            )

    async def test_raises_validation_error_when_redirect_uris_missing(self):
        with pytest.raises(ClientMetadataValidationError, match="redirect_uris"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, {"client_name": "App"}),
            )

    async def test_raises_validation_error_when_client_name_missing(self):
        with pytest.raises(ClientMetadataValidationError, match="client_name"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, {"redirect_uris": ["https://myapp.com/cb"]}),
            )

    async def test_raises_validation_error_for_http_url_when_not_allowed(self):
        with pytest.raises(ClientMetadataValidationError, match="https_required"):
            await fetch_client_metadata(
                "http://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, _VALID),
            )

    async def test_allows_http_when_explicitly_permitted(self):
        result = await fetch_client_metadata(
            "http://localhost/meta.json",
            allow_http=True,
            _transport=_transport(200, _VALID),
        )
        assert result.client_name == "My MCP App"
