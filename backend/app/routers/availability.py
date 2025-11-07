from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import redis_client as redis_module
from backend.app.db.session import get_session
from backend.app.routers.schemas import AvailabilityCheckIn, AvailabilityCheckOut

HOLD_TTL_SECONDS = 300
MAX_ALT_SEARCH = 32
ALT_LOOKAHEAD = 4

router = APIRouter()


def _slot_key(start_utc: datetime, end_utc: datetime, restaurant_id: str, party_size: int) -> str:
    return (
        f"hold:{restaurant_id}:"
        f"{start_utc.strftime('%Y%m%d%H%M')}:"
        f"{end_utc.strftime('%Y%m%d%H%M')}:"
        f"{party_size}"
    )


async def _capacity_summary(
    session: AsyncSession,
    restaurant_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[dict | None, dict]:
    params = {
        "restaurant_id": restaurant_id,
        "start_ts": start_utc,
        "end_ts": end_utc,
    }
    cap_row = await session.execute(
        text(
            """
            SELECT max_covers, max_parties
            FROM capacity_rule
            WHERE restaurant_id = :restaurant_id
              AND tstzrange(start_ts, end_ts, '[)') && tstzrange(:start_ts, :end_ts, '[)')
            ORDER BY start_ts DESC
            LIMIT 1
            """
        ),
        params,
    )
    capacity = cap_row.mappings().one_or_none()

    summary_row = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(party_size), 0) AS covers,
                   COUNT(*) AS parties
            FROM reservation
            WHERE restaurant_id = :restaurant_id
              AND status = 'confirmed'
              AND tstzrange(start_ts, end_ts, '[)') && tstzrange(:start_ts, :end_ts, '[)')
            """
        ),
        params,
    )
    usage = summary_row.mappings().one()
    return capacity, usage


async def _slot_available(
    session: AsyncSession,
    restaurant_id: str,
    start_utc: datetime,
    end_utc: datetime,
    requested_party: int,
) -> bool:
    capacity, usage = await _capacity_summary(session, restaurant_id, start_utc, end_utc)
    if capacity is None:
        return False

    covers = usage["covers"] + requested_party
    parties = usage["parties"] + 1
    if covers > capacity["max_covers"] or parties > capacity["max_parties"]:
        return False

    existing = await session.execute(
        text(
            """
            SELECT 1
            FROM reservation
            WHERE restaurant_id = :restaurant_id
              AND slot_id = :slot_id
              AND shard = 'A'
            LIMIT 1
            """
        ),
        {
            "restaurant_id": restaurant_id,
            "slot_id": f"{start_utc.strftime('%Y%m%d%H%M')}-{end_utc.strftime('%Y%m%d%H%M')}",
        },
    )
    return existing.first() is None


async def _build_alternates(
    session: AsyncSession,
    restaurant_id: str,
    start_utc: datetime,
    duration: timedelta,
    party_size: int,
) -> list[str]:
    alts: list[str] = []
    cursor = start_utc
    checked = 0
    while len(alts) < ALT_LOOKAHEAD and checked < MAX_ALT_SEARCH:
        cursor += timedelta(minutes=15)
        checked += 1
        alt_end = cursor + duration
        if await _slot_available(session, restaurant_id, cursor, alt_end, party_size):
            alts.append(cursor.isoformat())
    return alts


@router.post("/availability/check", response_model=AvailabilityCheckOut)
async def check_availability(
    payload: AvailabilityCheckIn,
    session: AsyncSession = Depends(get_session),
) -> AvailabilityCheckOut:
    if payload.start_ts.tzinfo is None or payload.start_ts.tzinfo.utcoffset(payload.start_ts) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_ts must include timezone information")

    if redis_module.redis_client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis unavailable")

    duration = timedelta(minutes=payload.duration_minutes)
    end_ts = payload.start_ts + duration

    start_utc = payload.start_ts.astimezone(timezone.utc)
    end_utc = end_ts.astimezone(timezone.utc)

    capacity, usage = await _capacity_summary(session, payload.restaurant_id, start_utc, end_utc)
    if capacity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No capacity rule configured for slot")

    projected_covers = usage["covers"] + payload.party_size
    projected_parties = usage["parties"] + 1
    slot_id = f"{start_utc.strftime('%Y%m%d%H%M')}-{end_utc.strftime('%Y%m%d%H%M')}"
    hold_key = _slot_key(start_utc, end_utc, payload.restaurant_id, payload.party_size)

    existing_hold = await redis_module.redis_client.exists(hold_key)
    existing_reservation = await session.execute(
        text(
            """
            SELECT 1
            FROM reservation
            WHERE restaurant_id = :restaurant_id
              AND slot_id = :slot_id
              AND shard = 'A'
            LIMIT 1
            """
        ),
        {"restaurant_id": payload.restaurant_id, "slot_id": slot_id},
    )

    if (
        projected_covers > capacity["max_covers"]
        or projected_parties > capacity["max_parties"]
        or existing_hold
        or existing_reservation.first() is not None
    ):
        alternates = await _build_alternates(session, payload.restaurant_id, start_utc, duration, payload.party_size)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Slot unavailable",
                "alternates": alternates,
            },
        )

    hold_id = str(uuid4())
    hold_result = await redis_module.redis_client.set(
        hold_key,
        hold_id,
        nx=True,
        px=HOLD_TTL_SECONDS * 1000,
    )

    if not hold_result:
        alternates = await _build_alternates(session, payload.restaurant_id, start_utc, duration, payload.party_size)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Slot temporarily held by another request",
                "alternates": alternates,
            },
        )

    return AvailabilityCheckOut(
        hold_id=hold_id,
        restaurant_id=payload.restaurant_id,
        start_ts=start_utc,
        end_ts=end_utc,
        duration_minutes=payload.duration_minutes,
        expires_in_seconds=HOLD_TTL_SECONDS,
    )
