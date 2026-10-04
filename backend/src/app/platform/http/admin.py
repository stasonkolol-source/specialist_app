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
- Решения по агрегатам (кейс, санкция, Founding) — через use case, действием раздела
  (`run_action`).
- Названия справочников (LocalizedText) правит форма `LocalizedNameForm`: поле на каждую локаль;
  правка ставит `name_origin = admin`, и `cli seed` такое название больше не переписывает.
- Admin API (2.7b) правит те же строки через `apply_change`: проверки и побочные эффекты — того же
  раздела (его `on_model_change`, аудит, события, сброс снимка), но правка, аудит и события —
  одной транзакцией UoW, а не вслед за commit SQLAdmin. Чтение строк разделов — `AdminRows`.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, ClassVar, Final, override
from uuid import UUID

from dishka import AsyncContainer
from fastapi import Path, Query
from sqladmin import ModelView
from sqlalchemy import ColumnElement, RowMapping, Table, event, func, inspect, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, UOWTransaction
from starlette.requests import Request
from wtforms import Form, StringField
from wtforms.validators import DataRequired, Length

from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.db.types import NameOrigin
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.kernel.principal import Role

MODERATION: Final = frozenset({Role.MODERATOR, Role.ADMIN})
"""Кейсы и жалобы."""
SUPPORT: Final = frozenset({Role.SUPPORT, Role.MODERATOR, Role.ADMIN})
"""Пользователи и санкции."""
ADMIN: Final = frozenset({Role.ADMIN})
"""Справочники, контент-правила, журнал аудита — moderator и support их не видят."""

LOCKS_INFO: Final = "admin_locks"
"""Ключ `Session.info`: класс ORM → ключ advisory lock его импорта."""

INT4_MIN: Final = -(2**31)
"""Границы колонок integer и smallint для схем Admin API: число за ними — 422 до запроса, а не
DataError из базы (500). Ноль и отрицательный id в границах: такой строки просто нет — 404."""
INT4_MAX: Final = 2**31 - 1
SMALLINT_MAX: Final = 2**15 - 1
RowIdPath = Annotated[int, Path(ge=INT4_MIN, le=INT4_MAX)]
"""id строки справочника (integer) в пути Admin API."""
RowIdQuery = Annotated[int | None, Query(ge=INT4_MIN, le=INT4_MAX)]
"""id строки справочника (integer) в фильтре списка."""


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
        case LocalizedText():
            return value.to_mapping()
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

    help_text: ClassVar[str] = ""
    """Подсказка над таблицей раздела (шаблон admin/list.html)."""

    page_size = 50
    can_export = False
    list_template = "admin/list.html"

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
    """Первичный ключ строки: id у справочников, `key` у флагов и конфигурации клиентов."""
    identity = inspect(model).identity
    return identity[0] if identity else None


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


NAME_LOCALES: Final = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN, Locale.EN)
"""Поля формы названия по порядку; ru и sr-Cyrl обязательны (CHECK `name_required_locales`)."""
REQUIRED_NAME_LOCALES: Final = (Locale.RU, Locale.SR_CYRL)


def _name_field(locale: Locale) -> str:
    return "name_" + locale.value.lower().replace("-", "_")


class LocalizedNameForm(StaffModelView):
    """Раздел справочника с правкой названия (LocalizedText): поле на каждую локаль.

    Название в строке одно — JSONB `name`; форма разворачивает его в поля ru, sr-Cyrl, sr-Latn и
    en и собирает обратно. Пустая латиница — транслит кириллицы, как у сидов
    (`LocalizedText.with_sr_latn`). Изменившееся название ставит `name_origin = admin`: следующий
    `cli seed` его не перепишет (выбор шага 2.7b — тот же, что у контент-правил).
    """

    @override
    async def scaffold_form(self, rules: list[str] | None = None) -> type[Form]:
        base = await super().scaffold_form(rules)
        fields: dict[str, object] = {
            _name_field(Locale.RU): StringField(
                "Название (ru)", validators=[DataRequired(), Length(max=120)]
            ),
            _name_field(Locale.SR_CYRL): StringField(
                "Назив (sr-Cyrl)", validators=[DataRequired(), Length(max=120)]
            ),
            _name_field(Locale.SR_LATN): StringField(
                "Naziv (sr-Latn) — пусто: транслит из sr-Cyrl", validators=[Length(max=120)]
            ),
            _name_field(Locale.EN): StringField("Name (en)", validators=[Length(max=120)]),
        }
        return type(f"{base.__name__}Named", (base,), fields)

    @override
    async def get_form_data_for_edit(self, obj: Any) -> dict[str, Any]:
        data = await super().get_form_data_for_edit(obj)
        name: LocalizedText = obj.name
        data.update({_name_field(loc): name.values.get(loc, "") for loc in NAME_LOCALES})
        return data

    @override
    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        # поля локалей — не колонки: SQLAdmin записал бы их в строку как атрибуты
        raw = {loc: str(data.pop(_name_field(loc), "") or "") for loc in NAME_LOCALES}
        try:
            name = LocalizedText({loc: text for loc, text in raw.items() if text.strip()})
        except DomainValidationError:
            raise ValueError("Название не может быть пустым") from None
        name = name.with_sr_latn()
        if is_created or name.to_mapping() != model.name.to_mapping():
            data["name"] = name
            model.name_origin = NameOrigin.ADMIN
        await super().on_model_change(data, model, is_created, request)


class InvalidAdminChangeError(DomainValidationError):
    """Правку не приняли проверки раздела — те же, что у формы SQLAdmin (`reason` — почему)."""

    code = "invalid_admin_change"
    public_params = ("reason",)


async def apply_change(
    request: Request,
    view: StaffModelView,
    pk: object | None,
    patch: Mapping[str, Any],
    *,
    name: Mapping[Locale, str] | None = None,
) -> Any:
    """Правка строки раздела из Admin API тем же путём, что форма SQLAdmin (ADR-0020 §1, §4).

    Данные — как у формы правки: поля `form_columns` раздела с текущими значениями, поверх —
    `patch`; у раздела с названием — поля локалей (`name` поверх текущего). Дальше — хуки раздела
    (`on_model_change`: название и `name_origin`, проверка правила, кто менял), advisory lock
    импорта, аудит `<audit_entity>.created|updated` и события раздела — одной транзакцией с правкой;
    после commit — сброс снимка (`after_change`). `pk` None — новая строка. Строки нет — None;
    отказ проверки, ограничения или типа колонки — InvalidAdminChangeError (422).
    """
    container = container_of(request)
    uow = await container.get(UnitOfWork)
    session = await container.get(AsyncSession)
    audit = await container.get(AuditLog)
    clock = await container.get(Clock)
    created = pk is None
    model_cls: Any = view.model
    async with uow:
        if view.advisory_lock is not None:  # тот же замок, что у импорта `cli seed`
            await session.execute(select(func.pg_advisory_xact_lock(view.advisory_lock)))
        model = model_cls() if created else await session.get(model_cls, pk, with_for_update=True)
        if model is None:
            return None
        data: dict[str, Any] = {} if created else _form_values(view, model)
        data.update(patch)
        if isinstance(view, LocalizedNameForm):
            current = {} if created else dict(model.name.values)
            merged = {**current, **(name or {})}
            if not all(merged.get(loc, "").strip() for loc in REQUIRED_NAME_LOCALES):
                # у формы SQLAdmin это DataRequired полей ru и sr-Cyrl
                raise InvalidAdminChangeError(reason="Название: ru и sr-Cyrl обязательны")
            data.update({_name_field(loc): merged.get(loc, "") for loc in NAME_LOCALES})
        try:
            await view.on_model_change(data, model, created, request)
        except ValueError as error:
            raise InvalidAdminChangeError(reason=str(error)) from None
        for key, value in data.items():
            setattr(model, key, value)
        if created:
            session.add(model)
        try:
            await session.flush()
        except IntegrityError:
            raise InvalidAdminChangeError(
                reason="ограничение базы: такая запись уже есть или ссылка неверна"
            ) from None
        except DataError:  # число вне типа колонки: схемы ловят раньше, здесь — страховка
            raise InvalidAdminChangeError(reason="значение не подходит к типу поля") from None
        await session.refresh(model)  # значения от базы (updated_at, умолчания) — до ответа
        await audit.record(
            AuditEntry(
                action=f"{view.audit_entity}.{'created' if created else 'updated'}",
                actor_kind=ActorKind.STAFF,
                actor_id=staff_id(request),
                entity_type=view.audit_entity,
                entity_id=_uuid(model),
                changes={"id": _plain(_pk(model)), **jsonable(data)},
                ip=request.client.host if request.client else None,
            )
        )
        for item in view.change_events(model, clock.now()):
            uow.add_event(item)
    await view.after_change(model, request)
    return model


def as_row(model: Any) -> dict[str, Any]:
    """Строка ORM — словарём колонок, как у `AdminRows` (схемы ответа строят одно и то же)."""
    return {attr.key: getattr(model, attr.key) for attr in inspect(model).mapper.column_attrs}


def table_of(view: type[StaffModelView] | StaffModelView) -> Table:
    """Таблица раздела: роутеры Admin API модуля не импортируют ORM-модели (ADR-0020 §1)."""
    table: Table = view.model.__table__  # type: ignore[attr-defined]
    return table


def _form_values(view: StaffModelView, model: Any) -> dict[str, Any]:
    """Текущие значения полей формы правки раздела (`form_columns`)."""
    columns: Iterable[Any] = view.form_columns or ()
    keys = [column if isinstance(column, str) else column.key for column in columns]
    return {key: getattr(model, key) for key in keys}


class AdminRows(SqlQuery):
    """Строки разделов для Admin API: keyset по первичному ключу, фильтры — условиями Core."""

    async def page(
        self,
        table: Table,
        page: PageRequest,
        *where: ColumnElement[bool],
        key: str = "id",
        key_type: type = int,
        columns: Iterable[str] = (),
    ) -> Page[RowMapping]:
        """`columns` — только эти колонки (без границ районов и городов); пусто — все."""
        column = table.c[key]
        chosen = [table.c[name] for name in columns] or list(table.c)
        stmt = select(*chosen).where(*where).order_by(column).limit(page.limit + 1)
        if page.cursor is not None:
            (last,) = decode_cursor(page.cursor, (key_type,))
            stmt = stmt.where(column > last)
        rows = await self._fetch(stmt)
        items = tuple(rows[: page.limit])
        more = len(rows) > page.limit
        return Page(items=items, next_cursor=encode_cursor(items[-1][key]) if more else None)

    async def one(self, table: Table, value: object, *, key: str = "id") -> RowMapping | None:
        return await self._fetch_one(select(table).where(table.c[key] == value))


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
