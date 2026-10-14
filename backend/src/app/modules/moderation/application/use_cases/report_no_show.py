"""Тихая жалоба «не пришёл» (подписчик DealCancelled): клиент отменил идущую сделку с причиной
«исполнитель не выходит на связь» — «Не пришёл / нет связи → Отменить и выбрать другого» на S26
и в боте. Жалоба `no_show` на исполнителя от клиента — тем же CreateReport, что шторка S46, но без
неё: кейс P1 о человеке, санкция — по решению модератора, а не сразу.

Предложение «Договорились» (сделки не было), отмена исполнителем, системой или с другой причиной —
ничего. Лимит жалоб клиента исчерпан или аккаунт исполнителя удалён — жалобы нет: отмена важнее,
она уже прошла. Открытая жалоба того же клиента на того же исполнителя — она же (CreateReport).
"""

from dataclasses import dataclass
from typing import Final

import structlog

from app.modules.moderation.application.use_cases.create_report import (
    CreateReport,
    CreateReportCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.reports import ReportReason
from app.modules.moderation.errors import ReportsLimitError, ReportTargetNotFoundError
from app.platform.kernel.ids import UserId

CLIENT: Final = "client"
NO_CONTACT: Final = "no_contact"
"""DealCancelReason «не выходит на связь»: значения — строками события DealCancelled."""

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportNoShowCommand:
    client_id: UserId
    performer_id: UserId
    cancelled_by: str
    """`cancelled_by` события: `client`, `performer`, `system`, `moderator`."""
    reason: str
    proposal: bool


class ReportNoShow:
    def __init__(self, create_report: CreateReport) -> None:
        self._create_report = create_report

    async def __call__(self, cmd: ReportNoShowCommand) -> bool:
        """True — жалоба подана (или такая уже открыта)."""
        if cmd.proposal or cmd.cancelled_by != CLIENT or cmd.reason != NO_CONTACT:
            return False
        try:
            await self._create_report(
                CreateReportCommand(
                    reporter_id=cmd.client_id,
                    target_type=EntityType.USER,
                    target_id=cmd.performer_id,
                    reason=ReportReason.NO_SHOW,
                )
            )
        except (ReportsLimitError, ReportTargetNotFoundError) as exc:
            log.info("no_show_report_skipped", code=exc.code)
            return False
        return True
