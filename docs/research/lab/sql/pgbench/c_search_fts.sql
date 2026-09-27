\set t random(1, 10)
SELECT specialist_id, display_name, ts_rank_cd(search_tsv, q, 32) AS rank
FROM mp.specialist_search,
     public.q_all((ARRAY['электрик','vodoinstalater','маникюр','čišćenje stanova','selidbe','prevodilac','сантехник','manikir','moler','ремонт стиральных машин'])[:t]) q
WHERE search_tsv @@ q AND city_id = 1
ORDER BY rank DESC, specialist_id DESC LIMIT 20;
