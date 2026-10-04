"""Кейсы, ступени санкций и сигналы риска в PostgreSQL (DEVELOPMENT_PLAN 2.5a)."""

from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moderation.domain.cases import OPEN, Case, EntityType
from app.modules.moderation.domain.risk import RiskSignal
from app.modules.moderation.domain.sanctions import COUNTED, Sanction, SanctionStep
from app.modules.moderation.errors import (
    AppealAlreadyFiledError,
    CaseAlreadyOpenError,
    CaseNotFoundError,
)
from app.modules.moderation.infrastructure.models import CaseRow, RiskSignalRow, SanctionRow
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, MediaId, UserId


class SqlCaseRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def get_for_update(self, case_id: CaseId) -> Case:
        case = await self._locked(CaseRow.id == case_id)
        if case is None:
            raise CaseNotFoundError(case_id=case_id)
        return case

    async def open_for_entity(self, entity_type: EntityType, entity_id: UUID) -> Case | None:
        return await self._locked(
            CaseRow.entity_type == entity_type,
            CaseRow.entity_id == entity_id,
            CaseRow.status.in_(OPEN),
            CaseRow.appeal_of.is_(None),
        )

    async def appeal_for(self, case_id: CaseId) -> Case | None:
        return await self._locked(CaseRow.appeal_of == case_id)

    async def get(self, case_id: CaseId) -> Case | None:
        row = await self._session.get(CaseRow, case_id, populate_existing=True)
        return _to_domain(row) if row is not None else None

    async def add(self, case: Case) -> None:
        self._uow.require_active()
        row = CaseRow(id=case.id, created_at=case.opened_at)
        _apply(case, row)
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(
                err,
                {
                    "uq_cases_entity_open": CaseAlreadyOpenError,
                    "uq_cases_appeal_of": AppealAlreadyFiledError,
                },
            )
        self._uow.track(case)

    async def save(self, case: Case) -> None:
        self._uow.require_active()
        row = await self._session.get(CaseRow, case.id)
        if row is None:
            raise CaseNotFoundError(case_id=case.id)
        _apply(case, row)
        await self._session.flush()
        self._uow.track(case)

    async def _locked(self, *conditions: object) -> Case | None:
        self._uow.require_active()
        stmt = (
            select(CaseRow)
            .where(*conditions)  # type: ignore[arg-type]  # ColumnElement[bool] вызывающего
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        case = _to_domain(row)
        self._uow.track(case)
        return case


class SqlSanctionRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def counted(self, user_id: UserId, now: datetime) -> int:
        stmt = select(func.count()).where(
            SanctionRow.user_id == user_id,
            SanctionRow.step.in_(COUNTED),
            SanctionRow.revoked_at.is_(None),
            SanctionRow.expires_at > now,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def latest_case(self, user_id: UserId, steps: Collection[SanctionStep]) -> CaseId | None:
        stmt = (
            select(SanctionRow.case_id)
            .where(
                SanctionRow.user_id == user_id,
                SanctionRow.step.in_(steps),
                SanctionRow.revoked_at.is_(None),
            )
            .order_by(SanctionRow.created_at.desc())
            .limit(1)
        )
        found = (await self._session.execute(stmt)).scalar_one_or_none()
        return CaseId(found) if found is not None else None

    async def revoke_for_case(self, case_id: CaseId, now: datetime) -> int:
        self._uow.require_active()
        stmt = (
            update(SanctionRow)
            .where(SanctionRow.case_id == case_id, SanctionRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # CursorResult

    async def add(self, sanction: Sanction) -> None:
        self._uow.require_active()
        self._session.add(
            SanctionRow(
                user_id=sanction.user_id,
                case_id=sanction.case_id,
                step=sanction.step,
                restriction_id=sanction.restriction_id,
                created_at=sanction.created_at,
                expires_at=sanction.expires_at,
            )
        )
        await self._session.flush()


class SqlRiskSignals:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, signals: Sequence[RiskSignal]) -> int:
        self._uow.require_active()
        if not signals:
            return 0
        stmt = (
            insert(RiskSignalRow)
            .values(
                [
                    {
                        "user_id": signal.user_id,
                        "signal": signal.kind,
                        "weight": signal.weight,
                        "ref_type": signal.ref_type,
                        "ref_id": signal.ref_id,
                        "details": dict(signal.details),
                        "dedupe_key": signal.dedupe_key,
                    }
                    for signal in signals
                ]
            )
            .on_conflict_do_nothing(index_elements=[RiskSignalRow.dedupe_key])
            .returning(RiskSignalRow.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())


def _to_domain(row: CaseRow) -> Case:
    return Case(
        id=CaseId(row.id),
        queue=row.queue,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        subject_id=UserId(row.subject_id),
        trigger=row.trigger,
        status=row.status,
        opened_at=row.created_at,
        due_at=row.due_at,
        evidence=[dict(entry) for entry in row.evidence],
        media_ids=tuple(MediaId(media_id) for media_id in row.media_ids),
        appeal_of=CaseId(row.appeal_of) if row.appeal_of is not None else None,
        assigned_to=UserId(row.assigned_to) if row.assigned_to is not None else None,
        decided_by=UserId(row.decided_by) if row.decided_by is not None else None,
        reason_code=row.reason_code,
        policy_version=row.policy_version,
        decided_at=row.decided_at,
        notes=row.notes,
    )


def _apply(case: Case, row: CaseRow) -> None:
    row.queue = case.queue
    row.entity_type = case.entity_type
    row.entity_id = case.entity_id
    row.subject_id = case.subject_id
    row.trigger = case.trigger
    row.status = case.status
    row.due_at = case.due_at
    row.evidence = [dict(entry) for entry in case.evidence]
    row.media_ids = list(case.media_ids)
    row.appeal_of = case.appeal_of
    row.assigned_to = case.assigned_to
    row.decided_by = case.decided_by
    row.reason_code = case.reason_code
    row.policy_version = case.policy_version
    row.decided_at = case.decided_at
    row.notes = case.notes
