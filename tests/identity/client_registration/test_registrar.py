import json
from unittest.mock import patch

import httpx
import pytest

from app.identity.client_registration.models import ClientMetadata, RegisteredClient
from app.identity.client_registration.registrar import DcrRegistrationError, enroll_mcp_client


@pytest.fixture(autouse=True)
def _dcr_endpoint():
    with patch(
        "app.identity.client_registration.registrar.settings.DCR_REGISTRATION_ENDPOINT",
        "https://provider.example.com/register",
    ):
        yield


_METADATA = ClientMetadata(
    redirect_uris=["https://myapp.com/callback"],
    client_name="My MCP App",
    scope="mcp:tools:read",
)

_DCR_RESPONSE = {
    "client_id": "generated-abc",
    "client_secret": "secret-xyz",
}


def _transport(status: int, body: dict) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


class TestRegisterClient:
    async def test_returns_dcr_result_on_success(self):
        result = await enroll_mcp_client(_METADATA, _transport=_transport(201, _DCR_RESPONSE))
        assert isinstance(result, RegisteredClient)
        assert result.client_id == "generated-abc"
        assert result.client_secret == "secret-xyz"
        assert result.redirect_uris == _METADATA.redirect_uris

    async def test_raises_on_provider_401(self):
        with pytest.raises(DcrRegistrationError, match="401"):
            await enroll_mcp_client(_METADATA, _transport=_transport(401, {"error": "unauthorized"}))

    async def test_raises_on_provider_500(self):
        with pytest.raises(DcrRegistrationError, match="500"):
            await enroll_mcp_client(_METADATA, _transport=_transport(500, {"error": "server error"}))

    async def test_posts_with_correct_method(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            return httpx.Response(201, json=_DCR_RESPONSE)

        await enroll_mcp_client(_METADATA, _transport=httpx.MockTransport(handler))
        assert captured["method"] == "POST"

    async def test_body_contains_redirect_uris_and_client_name(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(201, json=_DCR_RESPONSE)

        await enroll_mcp_client(_METADATA, _transport=httpx.MockTransport(handler))
        assert captured["body"]["redirect_uris"] == ["https://myapp.com/callback"]
        assert captured["body"]["client_name"] == "My MCP App"
        assert captured["body"]["scope"] == "mcp:tools:read"
