from datetime import datetime

from pydantic import BaseModel, Field


class CommitReservationIn(BaseModel):
    restaurant_id: str
    name: str = Field(min_length=1, max_length=200)
    party_size: int = Field(ge=1, le=50)
    # ISO 8601 with offset, e.g. "2025-11-05T19:00:00-05:00"
    start_ts: datetime
    duration_minutes: int = Field(ge=15, le=240)
    source: str = Field(default="phone")
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: str | None = Field(default=None, max_length=254)
    notes: str | None = Field(default=None, max_length=1024)


class CommitReservationOut(BaseModel):
    id: str


class AvailabilityCheckIn(BaseModel):
    restaurant_id: str
    party_size: int = Field(ge=1, le=50)
    start_ts: datetime
    duration_minutes: int = Field(ge=15, le=240)


class AvailabilityCheckOut(BaseModel):
    hold_id: str
    restaurant_id: str
    start_ts: datetime
    end_ts: datetime
    duration_minutes: int
    expires_in_seconds: int
