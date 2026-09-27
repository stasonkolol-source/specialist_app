-- (e) search by specialist name with typo/diacritics/script-insensitivity: 'Djordje' vs 'Đorđe'/'Ђорђе'
EXPLAIN (ANALYZE, BUFFERS)
SELECT specialist_id, display_name, similarity(public.search_norm(display_name), public.search_norm('djordje j')) AS sim
FROM mp.specialist_search
WHERE public.search_norm(display_name) % public.search_norm('djordje j')
ORDER BY sim DESC
LIMIT 10;
