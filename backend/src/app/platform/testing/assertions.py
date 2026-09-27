"""Проверки для тестов агрегатов (ADR-0020 §2)."""

from app.platform.kernel.aggregate import AggregateRoot, aggregate_state


def assert_same_state(left: AggregateRoot, right: AggregateRoot) -> None:
    """Два экземпляра агрегата в одинаковом публичном состоянии (например, после round-trip)."""
    if type(left) is not type(right):
        raise AssertionError(f"different types: {type(left).__name__} != {type(right).__name__}")
    a, b = aggregate_state(left), aggregate_state(right)
    if a != b:
        diff = {k: (a.get(k), b.get(k)) for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
        raise AssertionError(f"aggregate state differs: {diff}")
