import logging
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("app.client_metadata")


class ClientMetadata(BaseModel):
    model_config = {"extra": "ignore"}

    redirect_uris: list[str]
    client_name: str
    scope: str | None = None
    grant_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    logo_uri: str | None = None
    contacts: list[str] | None = None


class ClientMetadataFetchError(Exception):
    pass


class ClientMetadataValidationError(Exception):
    pass


async def fetch_client_metadata(
    url: str,
    *,
    allow_http: bool = False,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> ClientMetadata:
    parsed = urlparse(url)
    if parsed.scheme == "http" and not allow_http:
        raise ClientMetadataValidationError("https_required")
    if parsed.scheme not in ("http", "https"):
        raise ClientMetadataValidationError("URL must use http or https scheme")

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
    except Exception as exc:
        raise ClientMetadataValidationError("Invalid JSON in metadata document") from exc

    if not data.get("redirect_uris"):
        raise ClientMetadataValidationError("redirect_uris is required and must be non-empty")
    if not data.get("client_name"):
        raise ClientMetadataValidationError("client_name is required")

    try:
        return ClientMetadata.model_validate(data)
    except ValidationError as exc:
        raise ClientMetadataValidationError(f"Invalid metadata document: {exc}") from exc
