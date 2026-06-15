import ipaddress
import logging
import socket
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("app.identity.client_registration")


def _default_resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _assert_public_host(host: str, resolve: Callable[[str], list[str]]) -> None:
    """Block SSRF: reject hosts that resolve to non-public addresses.

    The metadata URL comes from the caller (RFC 7591 client_id), so without this an
    attacker could point it at cloud metadata (169.254.169.254), localhost, or RFC 1918
    ranges. We resolve and reject private/loopback/link-local/reserved/multicast IPs.

    Residual: this validates at request time; a fully DNS-rebinding-proof client would
    also pin the connection to the resolved IP. Documented as a follow-up.
    """
    try:
        ips = resolve(host)
    except OSError as exc:
        raise ClientMetadataValidationError(f"cannot resolve host {host!r}") from exc
    if not ips:
        raise ClientMetadataValidationError(f"cannot resolve host {host!r}")
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise ClientMetadataValidationError("host resolves to a non-public address")


class ClientMetadata(BaseModel):
    model_config = {"extra": "ignore"}

    redirect_uris: list[str]
    client_name: str
    scope: str | None = None
    grant_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    logo_uri: str | None = None
    contacts: list[str] | None = None


class RegisteredClient(BaseModel):
    client_id: str
    client_secret: str
    redirect_uris: list[str]


class ClientMetadataFetchError(Exception):
    pass


class ClientMetadataValidationError(Exception):
    pass


async def fetch_client_metadata(
    url: str,
    *,
    allow_http: bool = False,
    _transport: httpx.AsyncBaseTransport | None = None,
    _resolve: Callable[[str], list[str]] | None = None,
) -> ClientMetadata:
    parsed = urlparse(url)
    if parsed.scheme == "http" and not allow_http:
        raise ClientMetadataValidationError("https_required")
    if parsed.scheme not in ("http", "https"):
        raise ClientMetadataValidationError("URL must use http or https scheme")
    if not parsed.hostname:
        raise ClientMetadataValidationError("URL must include a host")
    # SSRF guard in production. allow_http (DEBUG) relaxes it so local dev can fetch
    # metadata from localhost.
    if not allow_http:
        _assert_public_host(parsed.hostname, _resolve or _default_resolve)

    try:
        async with httpx.AsyncClient(timeout=5.0, transport=_transport) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ClientMetadataFetchError(f"Timeout fetching {url}") from exc
    except httpx.HTTPStatusError as exc:
        raise ClientMetadataFetchError(f"HTTP {exc.response.status_code} fetching {url}") from exc
    except httpx.HTTPError as exc:
        raise ClientMetadataFetchError(f"Error fetching {url}: {exc}") from exc

    content_type = resp.headers.get("content-type", "")
    if "application/json" not in content_type:
        raise ClientMetadataValidationError(f"Expected content-type application/json, got {content_type!r}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise ClientMetadataValidationError("Invalid JSON in metadata document") from exc

    if not data.get("redirect_uris"):
        raise ClientMetadataValidationError("redirect_uris is required and must be non-empty")
    if not data.get("client_name"):
        raise ClientMetadataValidationError("client_name is required")

    try:
        return ClientMetadata.model_validate(data)
    except ValidationError as exc:
        raise ClientMetadataValidationError(f"Invalid metadata document: {exc}") from exc
