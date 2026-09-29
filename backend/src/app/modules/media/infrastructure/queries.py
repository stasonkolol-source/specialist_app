"""Чтение media без блокировки (ADR-0020 §4, §5): GET /media/{id}, ссылки на части, complete.

Транзакция чтения закрывается сразу после запроса (SqlQuery): `complete` потом ждёт HEAD
хранилища, и соединение с БД в это время не висит «idle in transaction».
"""

from sqlalchemy import select

from app.modules.media.domain.asset import MediaAsset
from app.modules.media.infrastructure.models import AssetRow
from app.modules.media.infrastructure.repositories import to_domain, visible_to
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import MediaId, UserId


class SqlMediaQuery(SqlQuery):
    async def asset(self, owner_id: UserId, media_id: MediaId) -> MediaAsset | None:
        stmt = select(AssetRow).where(*visible_to(owner_id, media_id))
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        # в домен — до конца транзакции: после rollback строка ORM истекает
        asset = to_domain(row) if row is not None else None
        await self._release()
        return asset
