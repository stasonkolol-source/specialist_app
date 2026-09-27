# platform/http

Общие HTTP-детали для роутеров модулей (шаг 0.13b):

- `pagination.py` — `PageParams` (`?limit&cursor`) и `PageOut[T]` (`{items, next_cursor}`);
- `concurrency.py` — `IfMatch` (`If-Match: "<version>"` → `ensure_version` → 412) и `ETag`;
- `ratelimit.py` — зависимость `RateLimit(rate)` и заголовки `RateLimit-*`;
- `caching.py` — `cached_json`: публичный ответ с сильным ETag по телу, `If-None-Match` → 304
  (шаги 1.1, 1.3b);
- `money.py` — `MoneyOut` (`{"amount": 500000, "currency": "RSD"}`, шаг 1.3b).

Отображение ошибок (RFC 9457) и middleware — в `interfaces/http` (шаг 0.13a).
