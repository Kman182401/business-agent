-- Handy diagnostic queries for overlap checks and alternative slot discovery.

-- Check whether a proposed reservation overlaps:
-- Replace :restaurant_id with actual UUID.
SELECT id, name
FROM reservation
WHERE restaurant_id = :restaurant_id
  AND slot && tstzrange('2025-11-01 19:00:00-04'::timestamptz,
                        '2025-11-01 20:30:00-04'::timestamptz,
                        '[)');

-- Suggest the next available 15-minute slots for a 90-minute stay.
WITH wanted AS (
  SELECT generate_series(
    '2025-11-01 19:00:00-04'::timestamptz,
    '2025-11-01 20:00:00-04'::timestamptz,
    '15 minutes'
  ) AS candidate_start
)
SELECT candidate_start
FROM wanted w
LEFT JOIN reservation r
  ON r.restaurant_id = :restaurant_id
 AND r.slot && tstzrange(
       w.candidate_start,
       w.candidate_start + interval '90 minutes',
       '[)'
     )
WHERE r.id IS NULL
ORDER BY candidate_start
LIMIT 4;
