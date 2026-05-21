import logging

from app.config import settings
from app.identity.client_registration.models import RegisteredClient
from app.shared.store import Store

logger = logging.getLogger("app.identity.client_registration")


async def get(metadata_url: str, store: Store) -> RegisteredClient | None:
    value = await store.get(metadata_url)
    if value is None:
        return None
    return RegisteredClient.model_validate_json(value)


async def set(metadata_url: str, result: RegisteredClient, store: Store, ttl: int | None = None) -> None:
    await store.set(metadata_url, result.model_dump_json(), ttl=ttl or settings.CLIENT_REGISTRY_TTL)
