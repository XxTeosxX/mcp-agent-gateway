import time
from typing import Protocol


class Store(Protocol):
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def pop(self, key: str) -> str | None: ...
    async def clear(self) -> None: ...


class RedisStore:
    def __init__(self, redis, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl is not None:
            await self._redis.set(self._prefix + key, value, ex=ttl)
        else:
            await self._redis.set(self._prefix + key, value)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(self._prefix + key)

    async def pop(self, key: str) -> str | None:
        return await self._redis.getdel(self._prefix + key)

    async def clear(self) -> None:
        keys = [k async for k in self._redis.scan_iter(match=self._prefix + "*")]
        if keys:
            await self._redis.delete(*keys)


class InMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl is not None else None
        self._data[key] = (value, expires_at)

    async def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            del self._data[key]
            return None
        return value

    async def pop(self, key: str) -> str | None:
        entry = self._data.pop(key, None)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            return None
        return value

    async def clear(self) -> None:
        self._data.clear()


class StoreHolder:
    def __init__(self) -> None:
        self._store: Store | None = None

    def init(self, store: Store) -> None:
        self._store = store

    def get(self) -> Store:
        if self._store is None:
            raise RuntimeError("token_store not initialized — call init() in mcp_lifespan")
        return self._store


token_store = StoreHolder()
