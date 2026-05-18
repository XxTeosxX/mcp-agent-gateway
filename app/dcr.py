import httpx
from pydantic import BaseModel

from app.client_metadata import ClientMetadata
from app.config import settings


class DcrResult(BaseModel):
    client_id: str
    client_secret: str


class DcrRegistrationError(Exception):
    pass


async def register_client(
    metadata: ClientMetadata,
    *,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> DcrResult:
    payload: dict = {
        "redirect_uris": metadata.redirect_uris,
        "client_name": metadata.client_name,
    }
    if metadata.grant_types:
        payload["grant_types"] = metadata.grant_types
    if metadata.scope:
        payload["scope"] = metadata.scope
    if metadata.token_endpoint_auth_method:
        payload["token_endpoint_auth_method"] = metadata.token_endpoint_auth_method

    headers = {"Authorization": f"Bearer {settings.DCR_INITIAL_ACCESS_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=10.0, transport=_transport) as client:
            resp = await client.post(settings.DCR_REGISTRATION_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DcrRegistrationError(f"DCR registration failed with HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise DcrRegistrationError(f"DCR request error: {exc}") from exc

    data = resp.json()
    return DcrResult(client_id=data["client_id"], client_secret=data["client_secret"])
