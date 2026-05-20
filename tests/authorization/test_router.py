from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from fastapi.testclient import TestClient

from app.config import settings
from app.identity.client_registration.models import (
    ClientMetadata,
    ClientMetadataFetchError,
    ClientMetadataValidationError,
    RegisteredClient,
)
from app.identity.client_registration.registrar import DcrRegistrationError

_METADATA = ClientMetadata(
    redirect_uris=["https://myapp.com/callback"],
    client_name="My MCP App",
)
_DCR_RESULT = RegisteredClient(client_id="kc-abc", client_secret="secret")


def _fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _authorize_url(client_id: str, redirect_uri: str = "https://myapp.com/callback") -> str:
    return (
        f"/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&code_challenge=abc123"
        f"&code_challenge_method=S256"
        f"&state=xyz"
    )


class TestOAuthAuthorizationServerMetadata:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_issuer_is_gateway_base_url(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.json()["issuer"] == settings.GATEWAY_BASE_URL

    def test_authorization_endpoint_points_to_gateway(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.json()["authorization_endpoint"] == f"{settings.GATEWAY_BASE_URL}/oauth/authorize"

    def test_token_endpoint_points_to_issuer(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert settings.OAUTH_ISSUER_URL in resp.json()["token_endpoint"]

    def test_code_challenge_methods_includes_s256(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert "S256" in resp.json()["code_challenge_methods_supported"]


class TestOAuthAuthorize:
    def test_url_client_id_redirects_to_as(self, client: TestClient) -> None:
        with (
            patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=_METADATA)),
            patch("app.authorization.router.enroll_mcp_client", new=AsyncMock(return_value=_DCR_RESULT)),
            patch("app.authorization.router.get_redis", return_value=_fake_redis()),
        ):
            resp = client.get(
                _authorize_url("https://myapp.com/client-metadata.json"),
                follow_redirects=False,
            )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "protocol/openid-connect/auth" in location
        assert "kc-abc" in location

    def test_non_url_client_id_passes_through_to_as(self, client: TestClient) -> None:
        resp = client.get(_authorize_url("pre-registered-client"), follow_redirects=False)
        assert resp.status_code == 302
        assert "pre-registered-client" in resp.headers["location"]
        assert "protocol/openid-connect/auth" in resp.headers["location"]

    def test_cache_hit_skips_fetch_and_dcr(self, client: TestClient) -> None:
        fetch_mock = AsyncMock(return_value=_METADATA)
        dcr_mock = AsyncMock(return_value=_DCR_RESULT)
        cache: dict = {}

        async def fake_get(url, *, redis=None):
            return cache.get(url)

        async def fake_set(url, result, *, redis=None, ttl=None):
            cache[url] = result

        with (
            patch("app.authorization.router.fetch_client_metadata", new=fetch_mock),
            patch("app.authorization.router.enroll_mcp_client", new=dcr_mock),
            patch("app.identity.client_registration.repository.get", new=fake_get),
            patch("app.identity.client_registration.repository.set", new=fake_set),
        ):
            client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
            client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert fetch_mock.call_count == 1
        assert dcr_mock.call_count == 1

    def test_metadata_fetch_failure_returns_invalid_client(self, client: TestClient) -> None:
        with patch(
            "app.authorization.router.fetch_client_metadata",
            new=AsyncMock(side_effect=ClientMetadataFetchError("timeout")),
        ):
            resp = client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 302
        assert "error=invalid_client" in resp.headers["location"]
        assert "metadata_fetch_failed" in resp.headers["location"]

    def test_https_required_error_in_redirect(self, client: TestClient) -> None:
        with patch(
            "app.authorization.router.fetch_client_metadata",
            new=AsyncMock(side_effect=ClientMetadataValidationError("https_required")),
        ):
            resp = client.get(_authorize_url("http://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 302
        assert "https_required" in resp.headers["location"]

    def test_redirect_uri_not_in_metadata_returns_invalid_request(self, client: TestClient) -> None:
        metadata_other = ClientMetadata(
            redirect_uris=["https://other.com/callback"],
            client_name="App",
        )
        with (
            patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=metadata_other)),
            patch("app.authorization.router.get_redis", return_value=_fake_redis()),
        ):
            resp = client.get(
                _authorize_url(
                    "https://myapp.com/client-metadata.json",
                    redirect_uri="https://myapp.com/callback",
                ),
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "error=invalid_request" in resp.headers["location"]

    def test_dcr_failure_returns_server_error(self, client: TestClient) -> None:
        with (
            patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=_METADATA)),
            patch(
                "app.authorization.router.enroll_mcp_client",
                new=AsyncMock(side_effect=DcrRegistrationError("5xx")),
            ),
            patch("app.authorization.router.get_redis", return_value=_fake_redis()),
        ):
            resp = client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 302
        assert "error=server_error" in resp.headers["location"]
