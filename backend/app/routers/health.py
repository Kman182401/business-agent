from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import redis_client as redis_module
from backend.app.db.session import get_session


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Basic liveness probe."""
    return {"ok": True}


@router.get("/readiness")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    """Ensure Postgres and Redis are reachable."""
    if redis_module.redis_client is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    await session.execute(text("SELECT 1"))
    try:
        await redis_module.redis_client.ping()
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    return {"ready": True}
