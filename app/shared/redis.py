from redis.asyncio import Redis, from_url


async def get_redis(url: str, *, socket_timeout: float | None = 5.0) -> Redis:
    # socket_timeout guards normal (non-blocking) commands against a wedged
    # server. Pass socket_timeout=None for connections that issue blocking
    # reads (XREADGROUP/XREAD with BLOCK), otherwise the read timeout races the
    # BLOCK deadline and raises a spurious TimeoutError.
    client: Redis = from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=socket_timeout,
    )
    await client.ping()
    return client
