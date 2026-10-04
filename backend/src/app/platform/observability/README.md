# platform/observability

Логи structlog с маскированием, Sentry, метрики (шаги 0.4, 3.3).

- `metrics.py` — реестр процесса, общие метрики (HTTP RED, очереди, 429 Telegram) и
  `metrics_server`: экспорт на METRICS_HOST:METRICS_PORT, путь `/metrics`, только при заданном порту.
- `sentry.py` — `init_sentry` (окружение, релиз, тег `process`, маскирование `before_send`) и
  `send_test_event` для `cli sentry-test`.
- `masking.py` — ПД и секреты (токены, initData, телефоны, ping URL Healthchecks) в логах и Sentry.
