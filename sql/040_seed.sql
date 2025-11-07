-- Seed data for local development verification.

DO $$
DECLARE
  v_restaurant uuid;
  v_day int;
BEGIN
  SELECT id INTO v_restaurant
  FROM restaurant
  WHERE name = 'Demo Bistro'
  LIMIT 1;

  IF v_restaurant IS NULL THEN
    INSERT INTO restaurant (
      name,
      phone,
      timezone,
      address,
      handoff_number,
      locale_default
    )
    VALUES (
      'Demo Bistro',
      '+1-555-0100',
      'America/New_York',
      '123 Example Ave, New York, NY',
      '+1-555-0199',
      'en-US'
    )
    RETURNING id INTO v_restaurant;
  END IF;

  FOR v_day IN 0..6 LOOP
    INSERT INTO hours_rule (
      restaurant_id,
      day_of_week,
      open_time,
      close_time
    )
    SELECT v_restaurant, v_day, '16:00'::time, '22:00'::time
    WHERE NOT EXISTS (
      SELECT 1 FROM hours_rule
       WHERE restaurant_id = v_restaurant
         AND day_of_week = v_day
    );
  END LOOP;

  INSERT INTO capacity_rule (
    restaurant_id,
    start_ts,
    end_ts,
    max_covers,
    max_parties,
    party_min,
    party_max
  )
  SELECT
    v_restaurant,
    '2025-01-01 16:00:00-05'::timestamptz,
    '2026-01-01 23:00:00-05'::timestamptz,
    40,
    10,
    1,
    12
  WHERE NOT EXISTS (
    SELECT 1 FROM capacity_rule
    WHERE restaurant_id = v_restaurant
      AND start_ts = '2025-01-01 16:00:00-05'::timestamptz
      AND end_ts   = '2026-01-01 23:00:00-05'::timestamptz
  );
END;
$$;
