"""Параметры модуля media (ADR-0020 §3): собирает di.py из настроек."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaConfig:
    public_base_url: str | None
    """CDN публичных вариантов (`https://cdn.<domain>`). Нет — варианты отдаются presigned
    GET на VARIANT_URL_TTL: так в dev и тестах, где CDN нет."""


VARIANT_URL_TTL = timedelta(hours=1)
