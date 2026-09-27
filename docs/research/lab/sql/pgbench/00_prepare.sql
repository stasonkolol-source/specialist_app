-- helper for random specialist picks in write transactions
DROP TABLE IF EXISTS mp.bench_spec_ids;
CREATE TABLE mp.bench_spec_ids AS SELECT row_number() OVER (ORDER BY specialist_id)::int AS n, specialist_id FROM mp.specialist_search;
ALTER TABLE mp.bench_spec_ids ADD PRIMARY KEY (n);
ANALYZE mp.bench_spec_ids;
SELECT count(*) AS bench_spec_ids FROM mp.bench_spec_ids;
