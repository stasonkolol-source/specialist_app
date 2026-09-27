# platform/http

Общие HTTP-детали для роутеров модулей (шаг 0.13b):

- `pagination.py` — `PageParams` (`?limit&cursor`) и `PageOut[T]` (`{items, next_cursor}`);
- `concurrency.py` — `IfMatch` (`If-Match: "<version>"` → `ensure_version` → 412) и `ETag`;
- `ratelimit.py` — зависимость `RateLimit(rate)` и заголовки `RateLimit-*`.

Отображение ошибок (RFC 9457) и middleware — в `interfaces/http` (шаг 0.13a).
