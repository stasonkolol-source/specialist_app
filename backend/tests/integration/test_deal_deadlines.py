"""Сроки сделок (DEVELOPMENT_PLAN 6.1b; ARCHITECTURE §12.3) со сдвигом часов: периодические
проходы напоминают за 2 ч до времени, спрашивают «Работа выполнена?» после него (без времени —
через сутки), завершают сделку через 72 ч после отметки одной стороны и отменяют предложение
«Договорились» без ответа. Повторный проход ничего не меняет. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.deals.application.ports import DealSweep
from app.modules.deals.application.use_cases.sweep_deals import SweepDeals, SweepDealsCommand
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.identity import insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


@pytest.fixture
async def worker(settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def sql(worker: AsyncContainer, statement: str, **params: object) -> Any:
    """Выполнить и вернуть первую строку; у INSERT строк нет — None."""
    engine = await worker.get(AsyncEngine)
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return result.first() if result.returns_rows else None


async def parties(worker: AsyncContainer) -> tuple[UserId, UserId]:
    async with worker() as request:
        session = await request.get(AsyncSession)
        return await insert_user(session), await insert_user(session)


async def deal(worker: AsyncContainer, client: UserId, performer: UserId, **columns: str) -> UUID:
    """Сделка строкой; `columns` — колонка → SQL-выражение («now() - interval '4 hours'»)."""
    deal_id = new_id()
    values = {"status": "'agreed'", "agreed_at": "now()"} | columns
    names = ", ".join(values)
    exprs = ", ".join(values.values())
    await sql(
        worker,
        f"INSERT INTO deals.deals (id, client_id, performer_id, origin, title_snapshot, version,"
        f" {names}) VALUES (:id, :client, :performer, 'direct', 'Повесить люстру', 1, {exprs})",
        id=deal_id,
        client=client,
        performer=performer,
    )
    return deal_id


async def sweep(worker: AsyncContainer, kind: DealSweep) -> int:
    async with worker() as request:
        return await (await request.get(SweepDeals))(SweepDealsCommand(sweep=kind))


async def row(worker: AsyncContainer, deal_id: UUID) -> Any:
    return await sql(
        worker,
        "SELECT status, cancel_reason, reminded_at, completion_prompted_at, completed_at"
        " FROM deals.deals WHERE id = :id",
        id=deal_id,
    )


async def test_reminder_goes_once_two_hours_before(worker: AsyncContainer) -> None:
    client, performer = await parties(worker)
    soon = await deal(worker, client, performer, scheduled_at="now() + interval '90 minutes'")
    later = await deal(worker, client, performer, scheduled_at="now() + interval '5 hours'")

    await sweep(worker, DealSweep.REMIND)
    reminded = (await row(worker, soon)).reminded_at
    await sweep(worker, DealSweep.REMIND)  # повторный проход — та же отметка, без второго раза

    assert reminded is not None
    assert (await row(worker, soon)).reminded_at == reminded
    assert (await row(worker, later)).reminded_at is None


async def test_completion_prompt_after_the_time_or_a_day_later(worker: AsyncContainer) -> None:
    client, performer = await parties(worker)
    timed = await deal(worker, client, performer, scheduled_at="now() - interval '4 hours'")
    untimed = await deal(worker, client, performer, agreed_at="now() - interval '25 hours'")
    fresh = await deal(worker, client, performer, agreed_at="now() - interval '2 hours'")

    await sweep(worker, DealSweep.PROMPT)

    assert (await row(worker, timed)).completion_prompted_at is not None
    assert (await row(worker, untimed)).completion_prompted_at is not None
    assert (await row(worker, fresh)).completion_prompted_at is None


async def test_silent_party_three_days_completes(worker: AsyncContainer) -> None:
    client, performer = await parties(worker)
    marked = await deal(
        worker, client, performer, client_confirmed_at="now() - interval '73 hours'"
    )
    recent = await deal(worker, client, performer, client_confirmed_at="now() - interval '1 hour'")

    await sweep(worker, DealSweep.AUTO_COMPLETE)

    done = await row(worker, marked)
    assert (done.status, done.completed_at is not None) == ("completed", True)
    assert (await row(worker, recent)).status == "agreed"
    # DealCompleted ушёл подписчикам: факт сделки для уровня доверия
    assert (
        await run_queued(worker, "identity.record_completed_deal", user_id=client, by="client_id")
        == 1
    )


async def test_unanswered_proposal_expires(worker: AsyncContainer) -> None:
    client, performer = await parties(worker)
    old = await deal(
        worker,
        client,
        performer,
        status="'proposed'",
        agreed_at="NULL",
        proposed_by=f"'{performer}'",
        created_at="now() - interval '73 hours'",
    )
    new = await deal(
        worker, client, performer, status="'proposed'", agreed_at="NULL", proposed_by=f"'{client}'"
    )

    await sweep(worker, DealSweep.EXPIRE_PROPOSALS)

    expired = await row(worker, old)
    assert (expired.status, expired.cancel_reason) == ("cancelled", "expired")
    assert (await row(worker, new)).status == "proposed"
