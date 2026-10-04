"""Общие детали разделов админки (SQLAdmin, DEVELOPMENT_PLAN 2.7a–b, ADR-0020 §1, §4).

- Доступ к разделу — по ролям персонала (`identity.user_roles`): сотрудника кладёт в
  `request.state.staff` вход админки (interfaces/admin/auth.py) на каждом запросе; раздел без
  нужной роли не виден в меню и по прямой ссылке отвечает 403.
- Правка через SQLAdmin — только справочники и контент-правила. SQLAdmin открывает свою сессию и
  коммитит сам, поэтому аудит и события пишутся следом отдельной транзакцией
  (`record_admin_change`) — ADR-0020: исключение — SQLAdmin коммитит сам. Процесс упал между
  commit и записью — событие потеряется; это закрывают идемпотентный реиндекс и ночной
  `search.reconcile_index`.
- Запись справочника берёт тот же `pg_advisory_xact_lock`, что импорт `cli seed` (`AdminSession`:
  ключ — у раздела, `advisory_lock`), иначе импорт при деплое и правка перетёрли бы друг друга.
- Решения по агрегатам (кейс, санкция) — через use case, действием раздела (`run_action`).
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Final, override
from uuid import UUID

from dishka import AsyncContainer
from sqladmin import ModelView
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, UOWTransaction
from starlette.requests import Request

from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Role

MODERATION: Final = frozenset({Role.MODERATOR, Role.ADMIN})
"""Кейсы и жалобы."""
SUPPORT: Final = frozenset({Role.SUPPORT, Role.MODERATOR, Role.ADMIN})
"""Пользователи и санкции."""
ADMIN: Final = frozenset({Role.ADMIN})
"""Справочники, контент-правила, журнал аудита — moderator и support их не видят."""

LOCKS_INFO: Final = "admin_locks"
"""Ключ `Session.info`: класс ORM → ключ advisory lock его импорта."""


def staff_roles(request: Request) -> frozenset[Role]:
    staff = getattr(request.state, "staff", None)
    return frozenset(staff.roles) if staff is not None else frozenset()


def staff_id(request: Request) -> UserId:
    """Кто действует: вход админки положил сотрудника в запрос (без входа раздел не открыть)."""
    return UserId(request.state.staff.user_id)


def container_of(request: Request) -> AsyncContainer:
    """REQUEST-контейнер запроса (интеграция dishka кладёт его в `request.state`, ADR-0020 §4)."""
    container: AsyncContainer = request.state.dishka_container
    return container


async def record_admin_change(
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    changes: Mapping[str, object] | None = None,
    events: Iterable[DomainEvent] = (),
) -> None:
    """Аудит правки из админки и её события — отдельной транзакцией после commit SQLAdmin."""
    # ADR-0020: исключение — SQLAdmin коммитит сам
    container = container_of(request)
    uow = await container.get(UnitOfWork)
    audit = await container.get(AuditLog)
    async with uow:
        await audit.record(
            AuditEntry(
                action=action,
                actor_kind=ActorKind.STAFF,
                actor_id=staff_id(request),
                entity_type=entity_type,
                entity_id=entity_id,
                changes=changes,
                ip=request.client.host if request.client else None,
            )
        )
        for item in events:
            uow.add_event(item)


def jsonable(data: Mapping[str, Any]) -> dict[str, object]:
    """Поля формы SQLAdmin для `audit_log.changes`: простые типы как есть, остальное строкой."""
    return {key: _plain(value) for key, value in data.items()}


def _plain(value: object) -> object:
    match value:
        case None | bool() | int() | float() | str():
            return value
        case Enum():
            return value.value
        case Decimal() | UUID():
            return str(value)
        case datetime() | date():
            return value.isoformat()
        case list() | tuple():
            return [_plain(item) for item in value]
        case _:
            return str(value)


class StaffModelView(ModelView):
    """Раздел админки: роли доступа, ключ блокировки импорта и аудит каждой правки."""

    roles: ClassVar[frozenset[Role]] = ADMIN
    advisory_lock: ClassVar[int | None] = None
    """Ключ pg_advisory_xact_lock импорта сидов этого справочника; None — справочник без импорта."""
    audit_entity: ClassVar[str] = ""
    """`<модуль>.<объект>` в audit_log: действие — `<модуль>.<объект>.created|updated|deleted`."""

    page_size = 50
    can_export = False

    @override
    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & self.roles)

    @override
    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    def change_events(self, model: Any, now: datetime) -> Iterable[DomainEvent]:  # noqa: ARG002
        """События правки (`CatalogChanged`); по умолчанию — никаких."""
        return ()

    async def after_change(self, model: Any, request: Request) -> None:
        """После записи: сбросить снимок справочника этого процесса."""

    @override
    async def after_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        await record_admin_change(
            request,
            action=f"{self.audit_entity}.{'created' if is_created else 'updated'}",
            entity_type=self.audit_entity,
            entity_id=_uuid(model),
            changes={"id": _plain(_pk(model)), **jsonable(data)},
            events=self.change_events(model, await _now(request)),
        )
        await self.after_change(model, request)

    @override
    async def after_model_delete(self, model: Any, request: Request) -> None:
        await record_admin_change(
            request,
            action=f"{self.audit_entity}.deleted",
            entity_type=self.audit_entity,
            entity_id=_uuid(model),
            changes={"id": _plain(_pk(model))},
            events=self.change_events(model, await _now(request)),
        )
        await self.after_change(model, request)


async def _now(request: Request) -> datetime:
    clock: Clock = await container_of(request).get(Clock)
    now: datetime = clock.now()
    return now


def _pk(model: Any) -> object:
    return getattr(model, "id", None)


def _uuid(model: Any) -> UUID | None:
    pk = _pk(model)
    return pk if isinstance(pk, UUID) else None


async def run_action[T](
    request: Request, use_case: type[Callable[..., Awaitable[T]]], command: object
) -> T:
    """Действие раздела над агрегатом — use case из REQUEST-контейнера (ADR-0020 §1)."""
    handler: Callable[..., Awaitable[T]] = await container_of(request).get(use_case)
    result: T = await handler(command)
    return result


class AdminSession(Session):
    """Сессия SQLAdmin: перед записью справочника — advisory lock его импорта (`cli seed`)."""


@event.listens_for(AdminSession, "before_flush")
def _take_import_locks(session: Session, _flush: UOWTransaction, _instances: object) -> None:
    locks: Mapping[type, int] = session.info.get(LOCKS_INFO, {})
    if not locks:
        return
    touched = (*session.new, *session.dirty, *session.deleted)
    for key in sorted({locks[type(obj)] for obj in touched if type(obj) in locks}):
        session.execute(select(func.pg_advisory_xact_lock(key)))
