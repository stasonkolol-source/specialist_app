"""Фейк конфигурации клиентов для тестов (ADR-0020 §11)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

DRAFT_LEGAL_VERSIONS: Mapping[str, str] = {"terms": "draft-1", "privacy": "draft-1"}
"""Как в миграции platform_0003 (черновики). Версии фейка по умолчанию: тестам на фейке всё
равно, какая редакция действует в БД."""

CURRENT_LEGAL_VERSIONS: Mapping[str, str] = {"terms": "1", "privacy": "1"}
"""Действующие версии в БД после всех миграций: platform_0007 включила утверждённую редакцию
«1». С ними соглашаются тесты на настоящей БД (tests/plugins/identity.accept_rules)."""


@dataclass
class FakeLegalVersions:
    """LegalVersions: версии правовых документов задаёт тест."""

    versions: dict[str, str] = field(default_factory=lambda: dict(DRAFT_LEGAL_VERSIONS))

    async def legal_versions(self) -> Mapping[str, str]:
        return dict(self.versions)
