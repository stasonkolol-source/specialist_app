\set t random(1, 12)
WITH q AS (SELECT public.search_norm((ARRAY['элек','сант','vodo','čišć','мани','manik','selid','prev','мал','moler','стир','veš'])[:t]) AS n),
hits AS (
  SELECT t.category_id, t.term, 2.0 AS score FROM mp.category_term t, q WHERE t.term_norm LIKE q.n || '%'
  UNION ALL
  SELECT t.category_id, t.term, word_similarity(q.n, t.term_norm) FROM mp.category_term t, q WHERE q.n <% t.term_norm)
SELECT DISTINCT ON (category_id) category_id, term, score FROM hits ORDER BY category_id, score DESC LIMIT 10;
