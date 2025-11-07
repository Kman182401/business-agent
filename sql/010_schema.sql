-- Core schema for the Front Desk reservation system (Step 1).

CREATE TABLE IF NOT EXISTS restaurant (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name            text NOT NULL,
  phone           text NOT NULL,
  timezone        text NOT NULL,
  address         text,
  handoff_number  text,
  locale_default  text NOT NULL DEFAULT 'en-US',
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hours_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id uuid NOT NULL REFERENCES restaurant(id) ON DELETE CASCADE,
  day_of_week int NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  open_time time NOT NULL,
  close_time time NOT NULL
);

CREATE TABLE IF NOT EXISTS blackout (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id uuid NOT NULL REFERENCES restaurant(id) ON DELETE CASCADE,
  start_ts timestamptz NOT NULL,
  end_ts   timestamptz NOT NULL,
  reason   text,
  CHECK (start_ts < end_ts)
);

CREATE TABLE IF NOT EXISTS capacity_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id uuid NOT NULL REFERENCES restaurant(id) ON DELETE CASCADE,
  start_ts timestamptz NOT NULL,
  end_ts   timestamptz NOT NULL,
  max_covers  int NOT NULL CHECK (max_covers  > 0),
  max_parties int NOT NULL CHECK (max_parties > 0),
  party_min   int NOT NULL DEFAULT 1 CHECK (party_min >= 1),
  party_max   int NOT NULL DEFAULT 12 CHECK (party_max >= party_min),
  CHECK (start_ts < end_ts)
);

CREATE TABLE IF NOT EXISTS reservation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id uuid NOT NULL REFERENCES restaurant(id) ON DELETE CASCADE,
  name         text NOT NULL,
  party_size   int  NOT NULL CHECK (party_size > 0),
  start_ts     timestamptz NOT NULL,
  end_ts       timestamptz NOT NULL,
  status       text NOT NULL CHECK (status IN ('pending','confirmed','cancelled')),
  source       text NOT NULL CHECK (source IN ('phone','web','staff')),
  contact_phone text,
  contact_email text,
  notes         text,
  slot_id      text NOT NULL,
  shard        text NOT NULL DEFAULT 'A',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (start_ts < end_ts)
);

CREATE INDEX IF NOT EXISTS reservation_restaurant_status_start_idx
  ON reservation (restaurant_id, status, start_ts);

CREATE INDEX IF NOT EXISTS reservation_slot_gist_idx
  ON reservation
  USING gist (tstzrange(start_ts, end_ts, '[)'));

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'reservation'::regclass
       AND conname = 'reservation_slot_unique'
  ) THEN
    ALTER TABLE reservation
      ADD CONSTRAINT reservation_slot_unique
        UNIQUE (restaurant_id, slot_id, shard);
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS event_log (
  ts timestamptz NOT NULL DEFAULT now(),
  restaurant_id uuid,
  type text NOT NULL,
  payload_json jsonb
);
