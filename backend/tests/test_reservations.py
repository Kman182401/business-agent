import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
from sqlalchemy.engine import make_url
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.app.core import redis_client as redis_module
from backend.app.core.redis_client import close_redis, init_redis
from backend.app.db.session import SessionLocal
from backend.app.main import app


pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
def seed_data():
    url_str = os.getenv("ALEMBIC_DATABASE_URL")
    if not url_str:
        raise RuntimeError("ALEMBIC_DATABASE_URL must be set for tests")

    url = make_url(url_str)
    conn = psycopg2.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username or "app_owner",
        password=url.password,
        dbname=url.database or "frontdesk",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT id FROM restaurant LIMIT 1")
    if cur.fetchone():
        cur.close()
        conn.close()
        return

    restaurant_id = str(uuid4())
    cur.execute(
        """
        INSERT INTO restaurant (id, name, phone, timezone, address, handoff_number, locale_default)
        VALUES (%s, 'Demo Bistro', '+1-555-0100', 'America/New_York', '123 Demo Ave', '+1-555-0199', 'en-US')
        """,
        (restaurant_id,),
    )

    for day in range(7):
        cur.execute(
            """
            INSERT INTO hours_rule (restaurant_id, day_of_week, open_time, close_time)
            VALUES (%s, %s, '16:00', '22:00')
            """,
            (restaurant_id, day),
        )

    cur.execute(
        """
        INSERT INTO capacity_rule (
          restaurant_id, start_ts, end_ts,
          max_covers, max_parties, party_min, party_max
        ) VALUES (
          %s,
          '2025-01-01 16:00:00-05',
          '2026-01-01 23:00:00-05',
          40,
          10,
          1,
          12
        )
        """,
        (restaurant_id,),
    )

    cur.execute(
        """
        INSERT INTO blackout (restaurant_id, start_ts, end_ts, reason)
        VALUES (%s, '2025-12-24 00:00:00-05', '2025-12-26 00:00:00-05', 'Christmas closure')
        """,
        (restaurant_id,),
    )

    cur.close()
    conn.close()


async def test_commit_reservation_success():
    await init_redis()
    try:
        async with SessionLocal() as session:
            restaurant_id = (
                await session.execute(text("SELECT id FROM restaurant LIMIT 1"))
            ).scalar_one()

        transport = ASGITransport(app=app)
        payload = {
            "restaurant_id": str(restaurant_id),
            "name": "Test Guest",
            "party_size": 2,
            "start_ts": "2025-11-05T19:00:00-05:00",
            "duration_minutes": 90,
            "source": "staff",
            "contact_phone": "+15550000",
            "contact_email": "guest@example.com",
            "notes": "pytest",
        }

        start = datetime.fromisoformat(payload["start_ts"]).astimezone(timezone.utc)
        end = start + timedelta(minutes=payload["duration_minutes"])
        hold_key = f"hold:{payload['restaurant_id']}:{start.strftime('%Y%m%d%H%M')}:{end.strftime('%Y%m%d%H%M')}:{payload['party_size']}"

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/reservations/commit", json=payload)

            assert response.status_code == 201, response.text
            reservation_id = response.json()["id"]

            second_response = await client.post("/api/v1/reservations/commit", json=payload)
            assert second_response.status_code == 409
            assert second_response.json()["detail"] == "Slot temporarily held by another request"

            if redis_module.redis_client:
                await redis_module.redis_client.delete(hold_key)

            third_response = await client.post("/api/v1/reservations/commit", json=payload)
            assert third_response.status_code == 409
            assert third_response.json()["detail"] == "Slot already booked"

        async with SessionLocal() as session:
            rows = await session.execute(
                text("SELECT status FROM reservation WHERE id = :id"),
                {"id": reservation_id},
            )
            status = rows.scalar_one()
            await session.execute(
                text("DELETE FROM reservation WHERE id = :id"),
                {"id": reservation_id},
            )
            await session.commit()

        assert status == "confirmed"

        if redis_module.redis_client:
            await redis_module.redis_client.delete(hold_key)
    finally:
        await close_redis()


async def test_health_endpoints():
    await init_redis()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/v1/healthz")
            readiness = await client.get("/api/v1/readiness")

        assert health.status_code == 200
        assert health.json() == {"ok": True}
        assert readiness.status_code == 200
        assert readiness.json() == {"ready": True}
    finally:
        await close_redis()


async def test_availability_hold_and_conflict():
    await init_redis()
    try:
        async with SessionLocal() as session:
            restaurant_id = (
                await session.execute(text("SELECT id FROM restaurant LIMIT 1"))
            ).scalar_one()

        transport = ASGITransport(app=app)
        payload = {
            "restaurant_id": str(restaurant_id),
            "party_size": 2,
            "start_ts": "2025-11-05T20:00:00-05:00",
            "duration_minutes": 90,
        }

        start = datetime.fromisoformat(payload["start_ts"]).astimezone(timezone.utc)
        end = start + timedelta(minutes=payload["duration_minutes"])
        hold_key = (
            f"hold:{payload['restaurant_id']}:"
            f"{start.strftime('%Y%m%d%H%M')}:{end.strftime('%Y%m%d%H%M')}:{payload['party_size']}"
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/v1/availability/check", json=payload)
            assert first.status_code == 200, first.text
            data = first.json()
            assert data["hold_id"]
            if redis_module.redis_client:
                ttl = await redis_module.redis_client.ttl(hold_key)
                assert ttl is not None and 0 < ttl <= 300

            second = await client.post("/api/v1/availability/check", json=payload)
            assert second.status_code == 409
            assert "alternates" in second.json()["detail"]

        if redis_module.redis_client:
            await redis_module.redis_client.delete(hold_key)
    finally:
        await close_redis()


async def test_parallel_commit_race():
    await init_redis()
    try:
        async with SessionLocal() as session:
            restaurant_id = (
                await session.execute(text("SELECT id FROM restaurant LIMIT 1"))
            ).scalar_one()

        payload = {
            "restaurant_id": str(restaurant_id),
            "name": "Parallel Guest",
            "party_size": 2,
            "start_ts": "2025-11-05T21:30:00-05:00",
            "duration_minutes": 90,
            "source": "staff",
        }

        start = datetime.fromisoformat(payload["start_ts"]).astimezone(timezone.utc)
        end = start + timedelta(minutes=payload["duration_minutes"])
        hold_key = (
            f"hold:{payload['restaurant_id']}:"
            f"{start.strftime('%Y%m%d%H%M')}:{end.strftime('%Y%m%d%H%M')}:{payload['party_size']}"
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:

            async def post_reservation():
                return await client.post("/api/v1/reservations/commit", json=payload)

            responses = await asyncio.gather(post_reservation(), post_reservation())

        status_codes = sorted(response.status_code for response in responses)
        assert status_codes == [201, 409]

        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM reservation WHERE restaurant_id = :restaurant_id AND start_ts = :start_ts"),
                {"restaurant_id": restaurant_id, "start_ts": start.astimezone(timezone.utc)},
            )
            await session.commit()

        if redis_module.redis_client:
            await redis_module.redis_client.delete(hold_key)
    finally:
        await close_redis()


async def test_capacity_enforced():
    await init_redis()
    payload_first = {
        "restaurant_id": None,
        "name": "Capacity Guest",
        "party_size": 4,
        "start_ts": "2025-11-05T22:30:00-05:00",
        "duration_minutes": 60,
        "source": "staff",
    }

    payload_second = {
        "restaurant_id": None,
        "name": "Capacity Guest 2",
        "party_size": 2,
        "start_ts": "2025-11-05T22:45:00-05:00",
        "duration_minutes": 60,
        "source": "staff",
    }

    start_first = datetime.fromisoformat(payload_first["start_ts"]).astimezone(timezone.utc)
    end_first = start_first + timedelta(minutes=payload_first["duration_minutes"])
    start_second = datetime.fromisoformat(payload_second["start_ts"]).astimezone(timezone.utc)
    end_second = start_second + timedelta(minutes=payload_second["duration_minutes"])

    async with SessionLocal() as session:
        restaurant_id = (
            await session.execute(text("SELECT id FROM restaurant LIMIT 1"))
        ).scalar_one()
        payload_first["restaurant_id"] = str(restaurant_id)
        payload_second["restaurant_id"] = str(restaurant_id)

        await session.execute(
            text(
                "DELETE FROM reservation WHERE restaurant_id = :restaurant_id AND start_ts = :start_ts"
            ),
            {"restaurant_id": restaurant_id, "start_ts": start_first},
        )
        await session.execute(
            text(
                "DELETE FROM reservation WHERE restaurant_id = :restaurant_id AND start_ts = :start_ts"
            ),
            {"restaurant_id": restaurant_id, "start_ts": start_second},
        )

        cap_row = await session.execute(
            text(
                """
                SELECT id, max_parties
                FROM capacity_rule
                WHERE restaurant_id = :restaurant_id
                ORDER BY start_ts ASC
                LIMIT 1
                """
            ),
            {"restaurant_id": restaurant_id},
        )
        capacity = cap_row.mappings().one()
        await session.execute(
            text("UPDATE capacity_rule SET max_parties = 1 WHERE id = :id"),
            {"id": capacity["id"]},
        )
        await session.commit()

    hold_key_first = (
        f"hold:{payload_first['restaurant_id']}:"
        f"{start_first.strftime('%Y%m%d%H%M')}:{end_first.strftime('%Y%m%d%H%M')}:{payload_first['party_size']}"
    )
    hold_key_second = (
        f"hold:{payload_second['restaurant_id']}:"
        f"{start_second.strftime('%Y%m%d%H%M')}:{end_second.strftime('%Y%m%d%H%M')}:{payload_second['party_size']}"
    )

    if redis_module.redis_client:
        await redis_module.redis_client.delete(hold_key_first)
        await redis_module.redis_client.delete(hold_key_second)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/v1/reservations/commit", json=payload_first)
            assert first.status_code == 201

            if redis_module.redis_client:
                await redis_module.redis_client.delete(hold_key_first)

            second = await client.post("/api/v1/reservations/commit", json=payload_second)
            assert second.status_code == 409
            assert second.json()["detail"] == "Capacity exceeded"

        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM reservation WHERE restaurant_id = :restaurant_id AND start_ts = :start_ts"),
                {"restaurant_id": restaurant_id, "start_ts": start_first},
            )
            await session.execute(
                text("DELETE FROM reservation WHERE restaurant_id = :restaurant_id AND start_ts = :start_ts"),
                {"restaurant_id": restaurant_id, "start_ts": start_second},
            )
            await session.commit()
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("UPDATE capacity_rule SET max_parties = :max_parties WHERE id = :id"),
                {"max_parties": capacity["max_parties"], "id": capacity["id"]},
            )
            await session.commit()

        if redis_module.redis_client:
            await redis_module.redis_client.delete(hold_key_first)
            await redis_module.redis_client.delete(hold_key_second)
        await close_redis()
