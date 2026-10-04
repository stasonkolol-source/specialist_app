"""Фасад модуля growth (ADR-0020 §6): реализация GrowthApi для BFF и других модулей."""

from app.modules.growth.api import GrowthApi, SharedLink, ShareRequest
from app.modules.growth.application.use_cases.create_share import (
    CreateShare,
    CreateShareCommand,
)


class GrowthFacade(GrowthApi):
    def __init__(self, create_share: CreateShare) -> None:
        self._create_share = create_share

    async def share(self, request: ShareRequest) -> SharedLink:
        return await self._create_share(
            CreateShareCommand(
                sharer_id=request.sharer_id,
                target=request.target,
                target_id=request.target_id,
                card=request.card,
            )
        )
