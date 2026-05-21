from redis.asyncio import Redis, from_url


async def get_redis(url: str) -> Redis:
    client: Redis = from_url(url, encoding="utf-8", decode_responses=True)
    await client.ping()
    return client
