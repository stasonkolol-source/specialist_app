"""Повторное использование presigned GET (перф-аудит): та же ссылка первую половину срока."""

from datetime import timedelta

import pytest

from app.platform.storage.presigned import PresignedUrls

pytestmark = pytest.mark.unit

HOUR = timedelta(hours=1)


class Signer:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"https://storage/object?X-Amz-Signature={self.calls}"


def test_same_object_gets_the_same_url_for_half_of_its_ttl() -> None:
    now = [0.0]
    urls, sign = PresignedUrls(monotonic=lambda: now[0]), Signer()

    first = urls.reuse(("media", "a.webp", HOUR), HOUR, sign)
    now[0] = 30 * 60 - 1
    assert urls.reuse(("media", "a.webp", HOUR), HOUR, sign) == first
    now[0] = 30 * 60
    assert urls.reuse(("media", "a.webp", HOUR), HOUR, sign) != first
    assert sign.calls == 2


def test_other_object_or_ttl_is_signed_separately() -> None:
    urls, sign = PresignedUrls(monotonic=lambda: 0.0), Signer()

    a = urls.reuse(("media", "a.webp", HOUR), HOUR, sign)
    b = urls.reuse(("media", "b.webp", HOUR), HOUR, sign)
    short = urls.reuse(("media", "a.webp", timedelta(minutes=5)), timedelta(minutes=5), sign)

    assert len({a, b, short}) == 3


def test_least_recently_used_url_is_evicted() -> None:
    urls, sign = PresignedUrls(size=2, monotonic=lambda: 0.0), Signer()

    a = urls.reuse("a", HOUR, sign)
    urls.reuse("b", HOUR, sign)
    assert urls.reuse("a", HOUR, sign) == a  # «a» снова свежая — вытесняется «b»
    urls.reuse("c", HOUR, sign)
    assert urls.reuse("a", HOUR, sign) == a
    assert sign.calls == 3
    urls.reuse("b", HOUR, sign)
    assert sign.calls == 4
