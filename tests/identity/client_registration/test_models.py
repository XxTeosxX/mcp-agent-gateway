import httpx
import pytest

from app.identity.client_registration.models import (
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


# Stub resolver so allow_http=False tests stay hermetic (no real DNS) while still
# exercising the SSRF guard's public-address path.
def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _transport(status: int, body: dict, content_type: str = "application/json") -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


class TestFetchClientMetadata:
    async def test_returns_client_metadata_on_success(self):
        result = await fetch_client_metadata(
            "https://myapp.com/meta.json", allow_http=False, _transport=_transport(200, _VALID), _resolve=_public
        )
        assert isinstance(result, ClientMetadata)
        assert result.redirect_uris == ["https://myapp.com/callback"]
        assert result.client_name == "My MCP App"

    async def test_optional_fields_are_none_when_absent(self):
        result = await fetch_client_metadata(
            "https://myapp.com/meta.json", allow_http=False, _transport=_transport(200, _VALID), _resolve=_public
        )
        assert result.scope == "mcp:tools:read mcp:tools:write"
        assert result.grant_types is None

    async def test_raises_fetch_error_on_404(self):
        with pytest.raises(ClientMetadataFetchError):
            await fetch_client_metadata(
                "https://myapp.com/meta.json", allow_http=False, _transport=_transport(404, {}), _resolve=_public
            )

    async def test_raises_fetch_error_on_timeout(self):
        def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        with pytest.raises(ClientMetadataFetchError, match="Timeout"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=httpx.MockTransport(timeout_handler),
                _resolve=_public,
            )

    async def test_raises_validation_error_on_wrong_content_type(self):
        with pytest.raises(ClientMetadataValidationError, match="application/json"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, _VALID, content_type="text/html"),
                _resolve=_public,
            )

    async def test_raises_validation_error_when_redirect_uris_missing(self):
        with pytest.raises(ClientMetadataValidationError, match="redirect_uris"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, {"client_name": "App"}),
                _resolve=_public,
            )

    async def test_raises_validation_error_when_client_name_missing(self):
        with pytest.raises(ClientMetadataValidationError, match="client_name"):
            await fetch_client_metadata(
                "https://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, {"redirect_uris": ["https://myapp.com/cb"]}),
                _resolve=_public,
            )

    async def test_raises_validation_error_for_http_url_when_not_allowed(self):
        with pytest.raises(ClientMetadataValidationError, match="https_required"):
            await fetch_client_metadata(
                "http://myapp.com/meta.json",
                allow_http=False,
                _transport=_transport(200, _VALID),
                _resolve=_public,
            )

    async def test_allows_http_when_explicitly_permitted(self):
        result = await fetch_client_metadata(
            "http://localhost/meta.json",
            allow_http=True,
            _transport=_transport(200, _VALID),
        )
        assert result.client_name == "My MCP App"


class TestSsrfGuard:
    """The metadata URL is caller-supplied, so the host must not resolve to a
    private/loopback/link-local address (SSRF)."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/meta.json",  # loopback
            "https://169.254.169.254/meta.json",  # cloud metadata (link-local)
            "https://10.0.0.1/meta.json",  # RFC 1918 private
            "https://192.168.1.1/meta.json",  # RFC 1918 private
            "https://[::1]/meta.json",  # IPv6 loopback
        ],
    )
    async def test_blocks_non_public_ip_literals(self, url):
        # IP-literal hosts resolve locally (no network); the guard rejects them.
        with pytest.raises(ClientMetadataValidationError, match="non-public address"):
            await fetch_client_metadata(url, allow_http=False, _transport=_transport(200, _VALID))

    async def test_blocks_hostname_resolving_to_internal_ip(self):
        # DNS that points a public-looking name at an internal IP must be rejected.
        def _internal(_host: str) -> list[str]:
            return ["169.254.169.254"]

        with pytest.raises(ClientMetadataValidationError, match="non-public address"):
            await fetch_client_metadata(
                "https://metadata.evil.example/meta.json",
                allow_http=False,
                _transport=_transport(200, _VALID),
                _resolve=_internal,
            )

    async def test_rejects_url_without_host(self):
        with pytest.raises(ClientMetadataValidationError, match="host"):
            await fetch_client_metadata("https:///meta.json", allow_http=False, _resolve=_public)

    async def test_debug_mode_relaxes_guard_for_localhost(self):
        # allow_http (DEBUG) lets local dev fetch metadata from localhost.
        result = await fetch_client_metadata(
            "http://127.0.0.1/meta.json", allow_http=True, _transport=_transport(200, _VALID)
        )
        assert result.client_name == "My MCP App"
