"""Продуктовая аналитика (DEVELOPMENT_PLAN 1.7, ARCHITECTURE §16.5): серверные события → PostHog EU.

- port.py — порт Analytics и событие AnalyticsEvent;
- events.py — таксономия: какие события есть, их свойства и какие метрики PRODUCT из них
  считаются (у каждой метрики — шаг-источник);
- posthog.py — адаптер PostHog EU, fake.py — фейк для dev и тестов (события в лог);
- tasks.py — задачи-подписчики доменных событий: событие уходит только после commit
  (задача ставится в той же транзакции) и не уходит при rollback.
- liquidity.py, beta_report.py, alerts.py — метрики ворот беты SQL под ролью readonly
  (`cli beta-report`) и алерт response rate@4h (6.6);
- dashboard.py — дашборд ликвидности PostHog как код, posthog_dashboard.py — его применение
  через REST API (`cli posthog-dashboard`, 6.6).

Без персональных данных: `distinct_id` — внутренний UUID, свойства — только значения из
закрытых списков, флаги, счётчики и id справочников; device ID и IP не отправляем.
"""
