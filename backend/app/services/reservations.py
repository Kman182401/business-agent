from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def commit_reservation(
    session: AsyncSession,
    *,
    restaurant_id: str,
    name: str,
    party_size: int,
    start_ts: datetime,
    duration_minutes: int,
    source: str,
    contact_phone: str | None,
    contact_email: str | None,
    notes: str | None,
) -> str:
    """Invoke the commit_reservation() SQL function and return the new reservation id."""
    end_ts = start_ts + timedelta(minutes=duration_minutes)

    query = text(
        """
        SELECT commit_reservation(
          :restaurant_id, :name, :party, :start_ts, :end_ts,
          :source, :phone, :email, :notes
        ) AS reservation_id
        """
    )

    result = await session.execute(
        query,
        {
            "restaurant_id": restaurant_id,
            "name": name,
            "party": party_size,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "source": source,
            "phone": contact_phone,
            "email": contact_email,
            "notes": notes,
        },
    )

    row = result.one()
    return str(row.reservation_id)
