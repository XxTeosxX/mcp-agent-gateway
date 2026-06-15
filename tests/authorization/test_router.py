from unittest.mock import AsyncMock, patch

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
_DCR_RESULT = RegisteredClient(
    client_id="kc-abc",
    client_secret="secret",
    redirect_uris=["https://myapp.com/callback"],
)


_VALID_CODE_CHALLENGE = "K7gNU3sdo-OL0wNhqoVWhr3g6s1xYv72ol_pe_Unols"


def _authorize_url(client_id: str, redirect_uri: str = "https://myapp.com/callback") -> str:
    return (
        f"/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&code_challenge={_VALID_CODE_CHALLENGE}"
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


class TestOAuthAuthorizationServerMetadata21:
    def test_only_authorization_code_and_client_credentials_supported(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        assert data["response_types_supported"] == ["code"]
        assert data["grant_types_supported"] == ["authorization_code", "client_credentials"]

    def test_s256_is_required_pkce_method(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        assert data.get("code_challenge_methods_supported") == ["S256"]


class TestOAuthAuthorize:
    def test_url_client_id_redirects_to_as(self, client: TestClient) -> None:
        with (
            patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=_METADATA)),
            patch("app.authorization.router.enroll_mcp_client", new=AsyncMock(return_value=_DCR_RESULT)),
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
        with (
            patch(
                "app.authorization.router.fetch_client_metadata",
                new=AsyncMock(return_value=_METADATA),
            ) as mock_fetch,
            patch("app.authorization.router.enroll_mcp_client", new=AsyncMock(return_value=_DCR_RESULT)),
        ):
            client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)

            client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert mock_fetch.await_count == 1

    def test_cache_hit_with_different_redirect_uri_returns_400_without_redirect(self, client: TestClient) -> None:
        # Regression: a cached DCR registration must still validate redirect_uri.
        # An attacker reusing the metadata URL with a different redirect_uri must not
        # receive a 302 to the attacker-controlled URI.
        with (
            patch(
                "app.authorization.router.fetch_client_metadata",
                new=AsyncMock(return_value=_METADATA),
            ) as mock_fetch,
            patch("app.authorization.router.enroll_mcp_client", new=AsyncMock(return_value=_DCR_RESULT)),
        ):
            client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
            resp = client.get(
                _authorize_url(
                    "https://myapp.com/client-metadata.json",
                    redirect_uri="https://evil.example/callback",
                ),
                follow_redirects=False,
            )
        assert mock_fetch.await_count == 1
        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert "evil.example" not in resp.text
        assert resp.json()["error"] == "invalid_request"
        assert resp.json()["error_description"] == "redirect_uri_not_in_metadata"

    def test_metadata_fetch_failure_returns_400_without_redirect(self, client: TestClient) -> None:
        with patch(
            "app.authorization.router.fetch_client_metadata",
            new=AsyncMock(side_effect=ClientMetadataFetchError("timeout")),
        ):
            resp = client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 400
        assert "location" not in resp.headers
        body = resp.json()
        assert body["error"] == "invalid_client"
        assert body["error_description"] == "metadata_fetch_failed"

    def test_https_required_error_returns_400_without_redirect(self, client: TestClient) -> None:
        with patch(
            "app.authorization.router.fetch_client_metadata",
            new=AsyncMock(side_effect=ClientMetadataValidationError("https_required")),
        ):
            resp = client.get(_authorize_url("http://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert resp.json()["error_description"] == "https_required"

    def test_redirect_uri_not_in_metadata_does_not_redirect_to_it(self, client: TestClient) -> None:
        # Regression: an attacker-supplied redirect_uri that fails the metadata allowlist
        # must NOT be echoed back in a 302 Location (open redirect).
        metadata_other = ClientMetadata(
            redirect_uris=["https://other.com/callback"],
            client_name="App",
        )
        with patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=metadata_other)):
            resp = client.get(
                _authorize_url(
                    "https://myapp.com/client-metadata.json",
                    redirect_uri="https://evil.example/callback",
                ),
                follow_redirects=False,
            )
        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert "evil.example" not in resp.text
        assert resp.json()["error"] == "invalid_request"

    def test_dcr_failure_returns_400_server_error(self, client: TestClient) -> None:
        with (
            patch("app.authorization.router.fetch_client_metadata", new=AsyncMock(return_value=_METADATA)),
            patch(
                "app.authorization.router.enroll_mcp_client",
                new=AsyncMock(side_effect=DcrRegistrationError("5xx")),
            ),
        ):
            resp = client.get(_authorize_url("https://myapp.com/client-metadata.json"), follow_redirects=False)
        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert resp.json()["error"] == "server_error"


class TestOAuthAuthorizePKCE:
    def test_missing_code_challenge_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=code"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    def test_missing_code_challenge_method_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=code"
            "&code_challenge=abc123"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    def test_plain_pkce_method_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=code"
            "&code_challenge=abc123"
            "&code_challenge_method=plain"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "only S256" in resp.json()["error_description"]

    def test_missing_state_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=code"
            "&code_challenge=abc123"
            "&code_challenge_method=S256",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    def test_missing_redirect_uri_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&response_type=code"
            "&code_challenge=abc123"
            "&code_challenge_method=S256"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"


class TestOAuthAuthorizeClientId:
    def test_missing_client_id_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize"
            "?redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=code"
            "&code_challenge=abc123"
            "&code_challenge_method=S256"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "location" not in resp.headers
        assert resp.json()["error"] == "invalid_request"
        assert resp.json()["error_description"] == "client_id is required"


class TestOAuthAuthorizeResponseType:
    def test_missing_response_type_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&code_challenge=abc123"
            "&code_challenge_method=S256"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"
        assert resp.json()["error_description"] == "response_type must be code"

    def test_invalid_response_type_returns_400(self, client: TestClient) -> None:
        resp = client.get(
            "/oauth/authorize?client_id=pre-registered"
            "&redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback"
            "&response_type=token"
            "&code_challenge=abc123"
            "&code_challenge_method=S256"
            "&state=xyz",
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"
        assert resp.json()["error_description"] == "response_type must be code"
