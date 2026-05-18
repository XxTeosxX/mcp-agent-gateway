import hashlib
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.dcr import DcrResult

logger = logging.getLogger("app.client_registry")

_redis: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _key(metadata_url: str) -> str:
    return f"client_registry:{hashlib.sha256(metadata_url.encode()).hexdigest()}"


async def get(metadata_url: str, *, redis: aioredis.Redis | None = None) -> DcrResult | None:
    r = redis if redis is not None else _redis
    try:
        value = await r.get(_key(metadata_url))
        if value is None:
            return None
        return DcrResult.model_validate_json(value)
    except Exception:
        logger.warning("Redis get failed for %s", metadata_url)
        return None


async def set(
    metadata_url: str,
    result: DcrResult,
    *,
    redis: aioredis.Redis | None = None,
    ttl: int | None = None,
) -> None:
    r = redis if redis is not None else _redis
    if r is None:
        return
    try:
        await r.set(
            _key(metadata_url),
            result.model_dump_json(),
            ex=ttl or settings.CLIENT_REGISTRY_TTL,
        )
    except Exception:
        logger.warning("Redis set failed for %s", metadata_url)
