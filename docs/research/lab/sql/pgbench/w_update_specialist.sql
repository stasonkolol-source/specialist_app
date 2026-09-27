\set n random(1, 49271)
BEGIN;
UPDATE mp.specialist s SET available_on = current_date, updated_at = now()
FROM mp.bench_spec_ids b WHERE b.n = :n AND s.id = b.specialist_id;
SELECT mp.refresh_specialist_search(ARRAY(SELECT specialist_id FROM mp.bench_spec_ids WHERE n = :n));
END;
