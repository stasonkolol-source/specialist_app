"""Фейк конфигурации клиентов для тестов (ADR-0020 §11)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

DRAFT_LEGAL_VERSIONS: Mapping[str, str] = {"terms": "draft-1", "privacy": "draft-1"}
"""Как в миграции platform_0003."""


@dataclass
class FakeLegalVersions:
    """LegalVersions: версии правовых документов задаёт тест."""

    versions: dict[str, str] = field(default_factory=lambda: dict(DRAFT_LEGAL_VERSIONS))

    async def legal_versions(self) -> Mapping[str, str]:
        return dict(self.versions)
