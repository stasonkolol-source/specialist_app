"""Чтение переписки (S29, S30; ADR-0020 §5): без блокировок, вне UoW. Порядок сообщений — по
UUIDv7 (`id` растёт со временем); курсор — id сообщения. Диалог в списке — одним запросом:
последнее сообщение (LATERAL) и непрочитанные (подзапрос) по индексу (conversation_id, id)."""

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import RowMapping, Select, and_, func, or_, select, true, tuple_

from app.modules.messaging.application.dto import ConversationView, MessagesPage
from app.modules.messaging.application.ports import Direction
from app.modules.messaging.domain.message import Message, MessageModeration
from app.modules.messaging.infrastructure.models import ConversationRow, MessageRow, ParticipantRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest

_C = ConversationRow.__table__.c
_P = ParticipantRow.__table__.c
_M = MessageRow.__table__.c
_OTHER = ParticipantRow.__table__.alias("other")
_LAST = MessageRow.__table__.alias("last_message")
_UNREAD = MessageRow.__table__.alias("unread_message")


class SqlConversationQueries(SqlQuery):
    async def mine(self, user_id: UserId, *, page: PageRequest) -> Page[ConversationView]:
        activity = func.coalesce(_C.last_message_at, _C.created_at)
        stmt = self._views(user_id)
        if page.cursor is not None:
            at, conversation_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(activity, _C.id) < tuple_(at, conversation_id))
        rows = await self._fetch(stmt.order_by(activity.desc(), _C.id.desc()).limit(page.limit + 1))
        items = [_view(row, user_id) for row in rows[: page.limit]]
        last = items[-1] if items else None
        cursor = None
        if len(rows) > page.limit and last is not None:
            cursor = encode_cursor(last.last_message_at or last.created_at, last.id)
        return Page(items=tuple(items), next_cursor=cursor)

    async def view(self, conversation_id: UUID, user_id: UserId) -> ConversationView | None:
        row = await self._fetch_one(self._views(user_id).where(_C.id == conversation_id))
        return _view(row, user_id) if row is not None else None

    async def messages(
        self,
        conversation_id: UUID,
        *,
        viewer_id: UserId,
        cursor: str | None,
        direction: Direction,
        limit: int,
    ) -> MessagesPage:
        base = select(MessageRow.__table__).where(_M.conversation_id == conversation_id)
        after = UUID(decode_cursor(cursor, (str,))[0]) if cursor else None
        if direction == "newer":
            # поллинг S30: новые после последнего показанного, по порядку
            stmt = base.where(_M.id > after) if after is not None else base
            rows = list(await self._fetch(stmt.order_by(_M.id).limit(limit)))
            items = tuple(_message(row, viewer_id) for row in rows)
            last = items[-1].id if items else after
            return MessagesPage(
                items=items, older=None, newer=encode_cursor(str(last)) if last else None
            )
        # первая страница — последние сообщения; дальше — более ранние от курсора
        stmt = base.where(_M.id < after) if after is not None else base
        rows = list(await self._fetch(stmt.order_by(_M.id.desc()).limit(limit + 1)))
        more = len(rows) > limit
        items = tuple(_message(row, viewer_id) for row in reversed(rows[:limit]))
        older = encode_cursor(str(items[0].id)) if more and items else None
        newer = encode_cursor(str(items[-1].id)) if items and after is None else None
        return MessagesPage(items=items, older=older, newer=newer)

    def _views(self, user_id: UserId) -> Select[Any]:  # Any: строки из колонок трёх таблиц
        last = (
            select(_LAST)
            .where(_LAST.c.conversation_id == _C.id)
            .order_by(_LAST.c.id.desc())
            .limit(1)
            .lateral("last")
        )
        unread = (
            select(func.count())
            .select_from(_UNREAD)
            .where(
                _UNREAD.c.conversation_id == _C.id,
                _UNREAD.c.sender_id != user_id,  # системные (без автора) — не в счёт
                _UNREAD.c.moderation != MessageModeration.HIDDEN,
                or_(_P.last_read_message_id.is_(None), _UNREAD.c.id > _P.last_read_message_id),
            )
            .scalar_subquery()
        )
        return (
            select(
                _C.id,
                _C.kind,
                _C.status,
                _C.job_id,
                _C.response_id,
                _C.deal_id,
                _C.created_at,
                _C.last_message_at,
                _P.role,
                _OTHER.c.user_id.label("counterpart_id"),
                unread.label("unread"),
                *(column.label(f"{LAST}{column.name}") for column in last.c),
            )
            .join_from(ConversationRow, ParticipantRow, _P.conversation_id == _C.id)
            .join(_OTHER, and_(_OTHER.c.conversation_id == _C.id, _OTHER.c.user_id != user_id))
            .outerjoin(last, true())
            .where(_P.user_id == user_id)
        )


LAST: Final = "last_"
"""Префикс колонок последнего сообщения в строке диалога."""


def _view(row: RowMapping, user_id: UserId) -> ConversationView:
    return ConversationView(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        my_role=row["role"],
        counterpart_id=UserId(row["counterpart_id"]),
        job_id=row["job_id"],
        response_id=row["response_id"],
        deal_id=row["deal_id"],
        last_message=_message(row, user_id, prefix=LAST) if row[f"{LAST}id"] else None,
        unread=int(row["unread"]),
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
    )


def _message(row: RowMapping, viewer_id: UserId, *, prefix: str = "") -> Message:
    """Сообщение глазами участника: скрытое модерацией — без текста, кроме своего."""
    sender_id = row[f"{prefix}sender_id"]
    mine = sender_id is not None and sender_id == viewer_id
    hidden = row[f"{prefix}moderation"] == MessageModeration.HIDDEN and not mine
    return Message(
        id=row[f"{prefix}id"],
        conversation_id=row[f"{prefix}conversation_id"],
        sender_id=UserId(sender_id) if sender_id is not None else None,
        kind=row[f"{prefix}kind"],
        body=None if hidden else row[f"{prefix}body"],
        created_at=row[f"{prefix}created_at"],
        client_msg_id=row[f"{prefix}client_msg_id"] if mine else None,
        payload={} if hidden else dict(row[f"{prefix}payload"]),
        moderation=row[f"{prefix}moderation"],
    )
