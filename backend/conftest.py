"""Общие фикстуры тестов backend: контейнеры и транзакция на тест (DEVELOPMENT_PLAN 0.5a)."""

pytest_plugins = ["tests.plugins.containers", "tests.plugins.database", "tests.plugins.settings"]
