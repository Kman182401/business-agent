from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.core.config import settings
from backend.app.core.redis_client import close_redis, init_redis
import backend.app.routers.availability as availability
import backend.app.routers.health as health
import backend.app.routers.reservations as reservations
import backend.app.routers.twilio_voice as twilio_voice
import backend.app.routers.twilio_realtime as twilio_realtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    try:
        yield
    finally:
        await close_redis()


app = FastAPI(
    title="AI Front Desk API",
    lifespan=lifespan,
)

app.include_router(health.router, prefix=settings.API_PREFIX)
app.include_router(availability.router, prefix=settings.API_PREFIX)
app.include_router(reservations.router, prefix=settings.API_PREFIX)
app.include_router(twilio_voice.router)
# Enable the realtime bridge when ready:
app.include_router(twilio_realtime.router)
