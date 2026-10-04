"""Адаптеры целей конвейера модерации (ARCHITECTURE §14.1, DEVELOPMENT_PLAN 2.6).

Адаптер — фасад модуля-владельца объекта для модерации: прочитать текст и файлы, опубликовать,
скрыть. Каждый контентный модуль добавляет свой адаптер `<тип>.py` в своём шаге: профиль (2.8a),
заявка (5.1), отклик (5.4), сообщение (6.3a), отзыв (7.2), фото и портфолио (6.7); здесь — реестр.
"""

from collections.abc import Mapping

from app.modules.moderation.application.ports import ModerationTarget, ModerationTargets
from app.modules.moderation.domain.cases import EntityType


class TargetRegistry(ModerationTargets):
    def __init__(self, targets: Mapping[EntityType, ModerationTarget]) -> None:
        self._targets = dict(targets)

    def get(self, entity_type: EntityType) -> ModerationTarget | None:
        return self._targets.get(entity_type)
