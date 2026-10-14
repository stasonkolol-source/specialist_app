"""Тихая жалоба «не пришёл» (moderation.report_no_show): клиент отменил идущую сделку «не выходит
на связь» — жалоба `no_show` на исполнителя без шторки S46; остальные отмены — ничего, лимит
жалоб не ломает отмену."""

from typing import cast

import pytest

from app.modules.moderation.application.use_cases.create_report import (
    CreateReport,
    CreateReportCommand,
)
from app.modules.moderation.application.use_cases.report_no_show import (
    ReportNoShow,
    ReportNoShowCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.reports import ReportReason
from app.modules.moderation.errors import ReportsLimitError
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

CLIENT, PERFORMER = UserId(new_id()), UserId(new_id())


class RecordingReports:
    def __init__(self, *, limit: bool = False) -> None:
        self.filed: list[CreateReportCommand] = []
        self._limit = limit

    async def __call__(self, cmd: CreateReportCommand) -> None:
        if self._limit:
            raise ReportsLimitError(retry_after=3600, limit=20)
        self.filed.append(cmd)


def command(
    *, cancelled_by: str = "client", reason: str = "no_contact", proposal: bool = False
) -> ReportNoShowCommand:
    return ReportNoShowCommand(
        client_id=CLIENT,
        performer_id=PERFORMER,
        cancelled_by=cancelled_by,
        reason=reason,
        proposal=proposal,
    )


async def test_client_cancelling_for_no_contact_reports_the_performer() -> None:
    reports = RecordingReports()

    assert await ReportNoShow(cast(CreateReport, reports))(command())

    [filed] = reports.filed
    assert (filed.reporter_id, filed.target_type, filed.target_id, filed.reason) == (
        CLIENT,
        EntityType.USER,
        PERFORMER,
        ReportReason.NO_SHOW,
    )


@pytest.mark.parametrize(
    "cancelled",
    [
        command(cancelled_by="performer"),
        command(cancelled_by="system"),
        command(reason="plans_changed"),
        command(proposal=True),  # предложение «Договорились» — сделки не было
    ],
    ids=["performer", "system", "other-reason", "proposal"],
)
async def test_other_cancellations_report_nothing(cancelled: ReportNoShowCommand) -> None:
    reports = RecordingReports()

    assert not await ReportNoShow(cast(CreateReport, reports))(cancelled)

    assert reports.filed == []


async def test_reports_limit_does_not_break_the_cancellation() -> None:
    assert not await ReportNoShow(cast(CreateReport, RecordingReports(limit=True)))(command())
