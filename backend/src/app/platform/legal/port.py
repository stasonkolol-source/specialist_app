"""Порт LegalLibrary: тексты правовых документов по версиям (DEVELOPMENT_PLAN 1.5a).

Какая версия действует — решает client-config (`legal_versions`, правит админка): по ней
identity сверяет согласие (1.4a). Тексты этой версии уходят клиенту в том же GET
/client-config (`legal_documents`): человек читает ровно ту редакцию, с которой соглашается.
Здесь — тексты всех опубликованных версий, по одной редакции на версию.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.platform.kernel.localized import Locale


class LegalDocument(StrEnum):
    """Документ; ключ совпадает с ключом `legal_versions` в client-config."""

    TERMS = "terms"
    """Правила площадки (галочка S02c вместе с политикой и 18+)."""
    PRIVACY = "privacy"
    """Политика конфиденциальности."""
    MODERATION = "moderation"
    """Политика модерации: как проверяем, коды причин, апелляции. Клиенту — с шагов 2.5."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LegalText:
    title: str
    body: str
    """Markdown без заголовка первого уровня; подстановки уже сделаны."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LegalEdition:
    """Редакция документа: одна версия со всеми переводами."""

    document: LegalDocument
    version: str
    published_on: date
    """Дата редакции."""
    texts: Mapping[Locale, LegalText]
    """ru есть всегда (исходник). sr-Cyrl — когда есть перевод, sr-Latn — его транслит."""


class LegalLibrary(Protocol):
    def edition(self, document: LegalDocument, version: str) -> LegalEdition | None:
        """Редакция версии; `None` — такой версии не публиковали."""
        ...

    def versions(self, document: LegalDocument) -> frozenset[str]:
        """Опубликованные версии документа."""
        ...
