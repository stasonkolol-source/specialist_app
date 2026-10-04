"""Порт RetentionHold (ARCHITECTURE §7.10, DEVELOPMENT_PLAN 2.12b): legal hold сроков хранения.

Правило хранения модуля не удаляет сущность, пока она нужна для разбора: о ней открыт кейс
модерации, а у сделки идёт спор. Реализует модуль на вершине DAG (moderation, спор — через
фасад deals); модуль с правилом о нём не знает, связывает dishka — как media.api.LegalHold и
identity.api.DeletionHold.
"""

from collections.abc import Collection
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class HoldKind(StrEnum):
    """Что спрашиваем: значения совпадают с `moderation.cases.entity_type`, кроме `deal`."""

    JOB = "job"
    RESPONSE = "response"
    MESSAGE = "message"
    DEAL = "deal"
    """Сделка со спором, который ещё идёт (6.1c): переписку по ней не удаляем."""


class RetentionHold(Protocol):
    async def held(self, kind: HoldKind, ids: Collection[UUID]) -> frozenset[UUID]:
        """Какие из сущностей удерживаются сейчас. Читает в транзакции вызывающего."""
        ...
