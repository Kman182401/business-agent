import redis.asyncio as redis

from backend.app.core.config import settings


redis_client: redis.Redis | None = None


async def init_redis() -> None:
    """Initialise a shared Redis connection."""
    global redis_client
    redis_client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )


async def close_redis() -> None:
    """Close the Redis connection if it was initialised."""
    if redis_client is not None:
        await redis_client.aclose()
