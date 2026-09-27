"""Снимок конфигурации клиентов и порт FeatureFlags.

Флаги называются `<модуль>.<флаг>` (ADR-0020 §10): `goods.segment`, `search.weights`.
Публичные флаги уходят клиенту в GET /client-config, остальные видит только backend.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class Flag:
    enabled: bool
    value: object | None = None
    public: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ClientConfigSnapshot:
    min_versions: Mapping[str, str] = field(default_factory=dict)
    legal_versions: Mapping[str, str] = field(default_factory=dict)
    flags: Mapping[str, Flag] = field(default_factory=dict)

    def public_flags(self) -> dict[str, bool]:
        return {key: flag.enabled for key, flag in sorted(self.flags.items()) if flag.public}


class FeatureFlags(Protocol):
    async def is_enabled(self, key: str) -> bool:
        """Флаг включён; неизвестный флаг выключен."""
        ...

    async def value(self, key: str) -> object | None:
        """Параметр флага (веса ранжирования и т. п.); None — не задан или выключен."""
        ...
