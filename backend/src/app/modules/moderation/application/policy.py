"""Версия политики модерации для решений (ADR-0016 §4: `reason_code` и `policy_version`).

Действующую версию задаёт client-config (`legal_versions.moderation`, правит админка), как
у правил и политики конфиденциальности. Пока её там нет — последняя опубликованная редакция
content/legal/moderation: политика модерации не требует согласия, и новая редакция действует
с публикации.
"""

from app.modules.moderation.application.ports import ModerationPolicy
from app.platform.config.port import LegalVersions
from app.platform.kernel.errors import ProgrammingError
from app.platform.legal.port import LegalDocument, LegalLibrary


class PublishedModerationPolicy(ModerationPolicy):
    def __init__(self, versions: LegalVersions, library: LegalLibrary) -> None:
        self._versions, self._library = versions, library

    async def version(self) -> str:
        document = LegalDocument.MODERATION
        if configured := (await self._versions.legal_versions()).get(document.value):
            return configured
        editions = [
            edition
            for version in self._library.versions(document)
            if (edition := self._library.edition(document, version)) is not None
        ]
        if not editions:
            raise ProgrammingError("moderation policy is not published: content/legal/moderation")
        return max(editions, key=lambda edition: (edition.published_on, edition.version)).version
