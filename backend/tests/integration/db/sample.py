"""Модуль-образец для тестов основы БД (DEVELOPMENT_PLAN 0.7b, ADR-0020 §5).

Показывает форму «агрегат + маппер + репозиторий + query-сервис», которой следуют модули.
UoW (uow.track) подключается в шаге 0.10.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, selectinload

from app.platform.db.base import (
    ModelBase,
    SoftDeleteMixin,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
    relation,
)
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.db.types import (
    GeoPointType,
    LocalizedTextType,
    MoneyAmount,
    localized_text_check,
    rsd_only,
    str_enum,
)
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.aggregate import StatusChange, VersionedAggregate
from app.platform.kernel.errors import ConflictError, NotFoundError
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import LocalizedText
from app.platform.kernel.money import Currency, Money
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef

SCHEMA = "sample"

# --- domain --------------------------------------------------------------------------------


class WidgetStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class WidgetNotFoundError(NotFoundError):
    code = "widget_not_found"


class DuplicateWidgetTitleError(ConflictError):
    code = "widget_title_taken"


class WidgetNotDraftError(ConflictError):
    code = "widget_not_draft"


@dataclass(frozen=True, slots=True, kw_only=True)
class WidgetPublished(DomainEvent):
    event_type = "sample.WidgetPublished"
    widget_id: UUID
    owner_id: UUID


ON_WIDGET_PUBLISHED: Final = TaskRef("sample.on_widget_published", WidgetPublished)


_ALLOWED: Final[Mapping[WidgetStatus, frozenset[WidgetStatus]]] = {
    WidgetStatus.DRAFT: frozenset({WidgetStatus.PUBLISHED}),
    WidgetStatus.PUBLISHED: frozenset(),
}


@dataclass(eq=False, kw_only=True)
class Widget(VersionedAggregate):
    id: UUID
    owner_id: UserId
    title: str
    name: LocalizedText
    price: Money
    location: GeoPoint
    status: WidgetStatus = WidgetStatus.DRAFT
    parts: list[str] = field(default_factory=list)
    deleted_at: datetime | None = None
    _history: list[StatusChange[WidgetStatus]] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def create(
        cls, *, owner_id: UserId, title: str, name: LocalizedText, price: Money, location: GeoPoint
    ) -> Widget:
        return cls(
            id=new_id(),
            owner_id=owner_id,
            title=title,
            name=name,
            price=price,
            location=location,
            version=1,
        )

    def publish(self, *, by: UserId, now: datetime) -> None:
        if WidgetStatus.PUBLISHED not in _ALLOWED[self.status]:
            raise WidgetNotDraftError(widget_id=self.id, status=self.status)
        self._history.append(
            StatusChange(
                from_=self.status, to=WidgetStatus.PUBLISHED, actor_id=by, reason=None, at=now
            )
        )
        self.status = WidgetStatus.PUBLISHED
        self._record(WidgetPublished(widget_id=self.id, owner_id=self.owner_id, occurred_at=now))

    def add_part(self, name: str) -> None:
        self.parts.append(name)

    def delete(self, *, now: datetime) -> None:
        self.deleted_at = now

    def pull_history(self) -> list[StatusChange[WidgetStatus]]:
        history, self._history = self._history, []
        return history


# --- infrastructure: ORM ------------------------------------------------------------------


class Base(ModelBase):
    __abstract__ = True
    metadata = module_metadata(SCHEMA)


class WidgetRow(UuidPkMixin, TimestampsMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "widgets"

    owner_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(120))
    name: Mapped[LocalizedText] = mapped_column(LocalizedTextType)
    price_amount: Mapped[int] = mapped_column(MoneyAmount)
    price_currency: Mapped[str] = mapped_column(String(3), default=Currency.RSD.value)
    location: Mapped[GeoPoint] = mapped_column(GeoPointType)
    status: Mapped[WidgetStatus] = mapped_column(str_enum(WidgetStatus, "status"))
    parts: Mapped[list[WidgetPartRow]] = relation(
        back_populates="widget", cascade="all, delete-orphan", order_by="WidgetPartRow.position"
    )

    __table_args__ = (
        Index(
            "uq_widgets_owner_id_title",
            "owner_id",
            "title",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_widgets_location", "location", postgresql_using="gist"),
        localized_text_check("name"),
        rsd_only("price_currency"),
    )


class WidgetPartRow(Base):
    __tablename__ = "widget_parts"

    widget_id: Mapped[UUID] = mapped_column(
        ForeignKey("widgets.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    widget: Mapped[WidgetRow] = relation(back_populates="parts")


class WidgetStatusHistoryRow(Base):
    __tablename__ = "status_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    widget_id: Mapped[UUID] = mapped_column(ForeignKey("widgets.id", ondelete="CASCADE"))
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID | None]
    reason: Mapped[str | None]
    at: Mapped[datetime]


# --- infrastructure: mappers and repository -----------------------------------------------


def to_domain(row: WidgetRow) -> Widget:
    return Widget(
        id=row.id,
        owner_id=UserId(row.owner_id),
        title=row.title,
        name=row.name,
        price=Money(row.price_amount, Currency(row.price_currency)),
        location=row.location,
        status=row.status,
        parts=[p.name for p in row.parts],
        deleted_at=row.deleted_at,
        version=row.version,
    )


def apply(widget: Widget, row: WidgetRow) -> None:
    row.owner_id = widget.owner_id
    row.title = widget.title
    row.name = widget.name
    row.price_amount = widget.price.amount
    row.price_currency = widget.price.currency.value
    row.location = widget.location
    row.status = widget.status
    row.deleted_at = widget.deleted_at
    current = [p.name for p in row.parts]
    if current != widget.parts:
        row.parts = [WidgetPartRow(position=i, name=n) for i, n in enumerate(widget.parts)]


WIDGET_CONSTRAINTS: ConstraintErrors = {
    "uq_widgets_owner_id_title": DuplicateWidgetTitleError,
}


class SqlWidgetRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def get(self, widget_id: UUID) -> Widget:
        widget = to_domain(await self._load(widget_id, for_update=False))
        self._uow.track(widget)
        return widget

    async def get_for_update(self, widget_id: UUID) -> Widget:
        widget = to_domain(await self._load(widget_id, for_update=True))
        self._uow.track(widget)
        return widget

    async def add(self, widget: Widget) -> None:
        self._uow.require_active()
        row = WidgetRow(id=widget.id, version=widget.version, parts=[])
        apply(widget, row)
        self._session.add(row)
        self._session.add_all(self._history_rows(widget))
        await self._flush()
        self._uow.track(widget)

    async def save(self, widget: Widget) -> None:
        self._uow.require_active()
        row = await self._session.get(WidgetRow, widget.id, options=[selectinload(WidgetRow.parts)])
        if row is None:
            raise WidgetNotFoundError(widget_id=widget.id)
        check_loaded_version(entity="widget", loaded=row.version, expected=widget.version)
        apply(widget, row)
        row.version = widget.version + 1
        self._session.add_all(self._history_rows(widget))
        await self._flush()
        widget.mark_persisted(version=row.version)
        self._uow.track(widget)

    async def _load(self, widget_id: UUID, *, for_update: bool) -> WidgetRow:
        stmt = (
            select(WidgetRow)
            .where(WidgetRow.id == widget_id)
            .options(selectinload(WidgetRow.parts))
            .execution_options(populate_existing=True)
        )
        stmt = stmt.where(WidgetRow.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise WidgetNotFoundError(widget_id=widget_id)
        return row

    def _history_rows(self, widget: Widget) -> list[WidgetStatusHistoryRow]:
        return [
            WidgetStatusHistoryRow(
                widget_id=widget.id,
                from_status=c.from_.value,
                to_status=c.to.value,
                actor_id=c.actor_id,
                reason=c.reason,
                at=c.at,
            )
            for c in widget.pull_history()
        ]

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, WIDGET_CONSTRAINTS)


# --- infrastructure: query service --------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class WidgetListItem:
    id: UUID
    title: str
    price: Money
    created_at: datetime


class SqlWidgetQuery(SqlQuery):
    async def list_for_owner(self, owner_id: UUID, page: PageRequest) -> Page[WidgetListItem]:
        w = WidgetRow.__table__.c
        stmt = (
            select(w.id, w.title, w.price_amount, w.price_currency, w.created_at)
            .where(w.owner_id == owner_id, w.deleted_at.is_(None))
            .order_by(w.created_at.desc(), w.id.desc())
            .limit(page.limit + 1)
        )
        if page.cursor:
            created, last_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(
                or_(w.created_at < created, and_(w.created_at == created, w.id < last_id))
            )
        rows = await self._fetch(stmt)
        items = tuple(
            WidgetListItem(
                id=r["id"],
                title=r["title"],
                price=Money(r["price_amount"], Currency(r["price_currency"])),
                created_at=r["created_at"],
            )
            for r in rows[: page.limit]
        )
        cursor = (
            encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > page.limit else None
        )
        return Page(items=items, next_cursor=cursor)

    async def boom(self) -> None:
        """Запрос, который падает на сервере (деление на ноль)."""
        await self._fetch(select(text("1 / 0")))
