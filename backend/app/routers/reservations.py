from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from asyncpg import exceptions as asyncpg_exc

from backend.app.core import redis_client as redis_module
from backend.app.db.session import get_session
from backend.app.routers.schemas import CommitReservationIn, CommitReservationOut
from backend.app.services.reservations import commit_reservation as commit_reservation_service


router = APIRouter()


def _slot_key(start_utc: str, end_utc: str, restaurant_id: str, party_size: int) -> str:
    return f"hold:{restaurant_id}:{start_utc}:{end_utc}:{party_size}"


@router.post("/reservations/commit", response_model=CommitReservationOut, status_code=status.HTTP_201_CREATED)
async def commit_endpoint(
    payload: CommitReservationIn,
    session: AsyncSession = Depends(get_session),
) -> CommitReservationOut:
    if payload.start_ts.tzinfo is None or payload.start_ts.tzinfo.utcoffset(payload.start_ts) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_ts must include timezone information")

    duration = timedelta(minutes=payload.duration_minutes)
    end_ts = payload.start_ts + duration

    start_utc = payload.start_ts.astimezone(timezone.utc)
    end_utc = end_ts.astimezone(timezone.utc)

    hold_key = _slot_key(
        start_utc.strftime("%Y%m%d%H%M"),
        end_utc.strftime("%Y%m%d%H%M"),
        payload.restaurant_id,
        payload.party_size,
    )

    if redis_module.redis_client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis unavailable")

    hold_acquired = await redis_module.redis_client.set(
        hold_key,
        "1",
        nx=True,
        px=300_000,
    )

    if not hold_acquired:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Slot temporarily held by another request")

    try:
        async with session.begin():
            reservation_id = await commit_reservation_service(
                session,
                restaurant_id=payload.restaurant_id,
                name=payload.name,
                party_size=payload.party_size,
                start_ts=start_utc,
                duration_minutes=payload.duration_minutes,
                source=payload.source,
                contact_phone=payload.contact_phone,
                contact_email=payload.contact_email,
                notes=payload.notes,
            )
    except DBAPIError as exc:
        await redis_module.redis_client.delete(hold_key)
        orig = getattr(exc, "orig", exc)
        message = str(orig)
        if isinstance(orig, asyncpg_exc.UniqueViolationError) or "Slot already booked" in message:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Slot already booked") from exc
        if "Capacity exceeded" in message:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Capacity exceeded") from exc
        if "No capacity rule" in message:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No capacity rule configured for slot") from exc
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error") from exc
    except Exception as exc:
        await redis_module.redis_client.delete(hold_key)
        if isinstance(exc, asyncpg_exc.UniqueViolationError) or "Slot already booked" in str(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Slot already booked") from exc
        raise

    return CommitReservationOut(id=reservation_id)
