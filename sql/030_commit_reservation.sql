-- Function that enforces capacity rules with advisory locks at commit time.

CREATE OR REPLACE FUNCTION commit_reservation(
  p_restaurant uuid,
  p_name text,
  p_party int,
  p_start timestamptz,
  p_end   timestamptz,
  p_source text,
  p_phone text,
  p_email text,
  p_notes text
) RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_id uuid := gen_random_uuid();
  v_slot_id text;
  v_bucket_start timestamptz;
  v_iter timestamptz;
  v_restaurant_hash int;
  v_capacity RECORD;
  v_proposed tstzrange := tstzrange(p_start, p_end, '[)');
  v_confirmed_covers int;
  v_confirmed_parties int;
BEGIN
  IF p_start >= p_end THEN
    RAISE EXCEPTION 'start_ts must be before end_ts';
  END IF;

  IF p_party <= 0 THEN
    RAISE EXCEPTION 'party size must be positive';
  END IF;

  v_slot_id :=
    to_char(date_trunc('minute', p_start), 'YYYYMMDDHH24MI') || '-' ||
    to_char(date_trunc('minute', p_end), 'YYYYMMDDHH24MI');

  v_restaurant_hash :=
    ((hashtextextended(p_restaurant::text, 0) >> 32)::int);

  v_bucket_start :=
    date_trunc('minute', p_start)
    - make_interval(mins => mod(extract(minute FROM p_start)::int, 15));

  v_iter := v_bucket_start;
  WHILE v_iter < p_end LOOP
    PERFORM pg_advisory_xact_lock(
      v_restaurant_hash,
      floor(extract(epoch FROM v_iter) / 900)::int
    );
    v_iter := v_iter + interval '15 minutes';
  END LOOP;

  IF EXISTS (
    SELECT 1
    FROM reservation r
    WHERE r.restaurant_id = p_restaurant
      AND r.slot_id = v_slot_id
      AND r.shard = 'A'
  ) THEN
    RAISE EXCEPTION 'Slot already booked';
  END IF;

  SELECT max_covers, max_parties
    INTO v_capacity
    FROM capacity_rule
   WHERE restaurant_id = p_restaurant
     AND tstzrange(start_ts, end_ts, '[)') && v_proposed
   ORDER BY start_ts DESC
   LIMIT 1;

  IF v_capacity IS NULL THEN
    RAISE EXCEPTION 'No capacity rule covers requested slot';
  END IF;

  SELECT COALESCE(SUM(party_size), 0), COUNT(*)
    INTO v_confirmed_covers, v_confirmed_parties
    FROM reservation
   WHERE restaurant_id = p_restaurant
     AND status = 'confirmed'
     AND tstzrange(start_ts, end_ts, '[)') && v_proposed;

  IF v_confirmed_covers + p_party > v_capacity.max_covers THEN
    RAISE EXCEPTION 'Capacity exceeded: covers % + % > %',
      v_confirmed_covers, p_party, v_capacity.max_covers;
  END IF;

  IF v_confirmed_parties + 1 > v_capacity.max_parties THEN
    RAISE EXCEPTION 'Capacity exceeded: parties % + 1 > %',
      v_confirmed_parties, v_capacity.max_parties;
  END IF;

  INSERT INTO reservation(
    id,
    restaurant_id,
    name,
    party_size,
    start_ts,
    end_ts,
    status,
    source,
    contact_phone,
    contact_email,
    notes,
    slot_id,
    shard
  )
  VALUES (
    v_id,
    p_restaurant,
    p_name,
    p_party,
    p_start,
    p_end,
    'confirmed',
    p_source,
    p_phone,
    p_email,
    p_notes,
    v_slot_id,
    'A'
  );

  RETURN v_id;
EXCEPTION
  WHEN unique_violation THEN
    RAISE EXCEPTION 'Slot already booked';
END;
$$;
