-- 05_geo_basics.sql — PostGIS basics for the product: geography(Point,4326), ST_DWithin in meters,
-- KNN (<->), point-in-polygon for districts, GiST, geography vs projected geometry.
-- The three named polygons below are COARSE SYNTHETIC approximations of Belgrade areas (not real borders).
\pset pager off
SET search_path = mp, public;
SET max_parallel_workers_per_gather = 0;

DROP TABLE IF EXISTS geo_demo_area;
CREATE TEMP TABLE geo_demo_area(name text, boundary geometry(Polygon, 4326));
INSERT INTO geo_demo_area VALUES
 ('Vračar (synthetic)',       ST_GeomFromText('POLYGON((20.463 44.806, 20.482 44.807, 20.496 44.797, 20.491 44.786, 20.470 44.785, 20.462 44.795, 20.463 44.806))', 4326)),
 ('Novi Beograd (synthetic)', ST_GeomFromText('POLYGON((20.370 44.800, 20.405 44.832, 20.447 44.829, 20.452 44.812, 20.430 44.795, 20.385 44.790, 20.370 44.800))', 4326)),
 ('Zemun (synthetic)',        ST_GeomFromText('POLYGON((20.365 44.838, 20.392 44.876, 20.425 44.872, 20.418 44.846, 20.405 44.832, 20.372 44.826, 20.365 44.838))', 4326));
CREATE INDEX ON geo_demo_area USING gist (boundary);

\echo '=== A. Point-in-polygon for landmarks (approximate coordinates)'
SELECT l.name AS landmark, coalesce(a.name, '-- none of the 3 --') AS area
FROM (VALUES ('Hram Svetog Save', 20.4689, 44.7981), ('Ušće Tower', 20.4368, 44.8157), ('Gardoš Tower', 20.4108, 44.8479),
             ('Trg Republike', 20.4602, 44.8166), ('Beogradska Arena', 20.4214, 44.8144)) l(name, lon, lat)
LEFT JOIN geo_demo_area a ON ST_Covers(a.boundary, ST_SetSRID(ST_MakePoint(l.lon, l.lat), 4326));

\echo '=== B. Distances on the spheroid (geography, meters)'
SELECT a.name->>'en' AS from_city, b.name->>'en' AS to_city, round((ST_Distance(a.center, b.center) / 1000.0)::numeric, 1) AS km
FROM city a JOIN city b ON b.id IN (2, 3, 4) WHERE a.id = 1;

\echo '=== C. Pitfall: ST_DWithin on geometry(4326) uses DEGREES, on geography uses METERS'
SELECT count(*) FILTER (WHERE ST_DWithin(location::geometry, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326), 5000)) AS geometry_4326_5000_degrees,
       count(*) FILTER (WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 5000)) AS geography_5000_meters,
       count(*) AS total
FROM specialist_search;

\echo '=== D. Radius count within 5 km: geography+GiST vs projected geometry (UTM 34N, EPSG:32634)+GiST vs no index'
CREATE INDEX IF NOT EXISTS ss_location_utm_gist ON specialist_search USING gist (ST_Transform(location::geometry, 32634));
ANALYZE specialist_search;
\echo '-- D1 geography + GiST'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT count(*) FROM specialist_search WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 5000);
\echo '-- D2 projected geometry (meters) + GiST expression index'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT count(*) FROM specialist_search
WHERE ST_DWithin(ST_Transform(location::geometry, 32634), ST_Transform(ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326), 32634), 5000);
\echo '-- D3 geography without index (seq scan)'
SET enable_indexscan = off; SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT count(*) FROM specialist_search WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography, 5000);
RESET enable_indexscan; RESET enable_bitmapscan;

\echo '=== E. KNN: 20 nearest specialists (GiST index-ordered scan with <->)'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT specialist_id, round(ST_Distance(location, x.p)) AS m
FROM specialist_search, (SELECT ST_SetSRID(ST_MakePoint(20.4612, 44.8125), 4326)::geography AS p) x
ORDER BY location <-> x.p LIMIT 20;

\echo '=== F. District membership for all 49k specialists (spatial join, GiST on district.boundary)'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT d.id, count(*) FROM specialist_search s JOIN district d ON ST_Covers(d.boundary, s.location::geometry) GROUP BY d.id;

DROP INDEX ss_location_utm_gist;
