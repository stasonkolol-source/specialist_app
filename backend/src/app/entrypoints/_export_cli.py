"""`cli export-user-data`: выгрузка данных пользователя по запросу (DEVELOPMENT_PLAN 2.12b).

Пользователь — по id или Telegram id. Разделы модулей собирает platform/privacy/export.py из
реестра (privacy.py модулей); запись в audit_log — там же.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.platform.settings import Settings

if TYPE_CHECKING:
    from app.modules.identity.api import IdentityApi


async def export_user_data(user_ref: str, *, note: str | None) -> dict[str, Any] | None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.identity.api import IdentityApi
    from app.platform.kernel.clock import Clock
    from app.platform.kernel.ids import UserId
    from app.platform.privacy.export import export_user_data as export

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            identity = await request.get(IdentityApi)
            user_id = await _resolve(identity, user_ref)
            if user_id is None or await identity.get_user(UserId(user_id)) is None:
                return None
        now = (await container.get(Clock)).now()
        return await export(container, user_id, now=now, note=note)
    finally:
        await container.close()


async def _resolve(identity: IdentityApi, user_ref: str) -> UUID | None:
    if user_ref.isdigit():
        user = await identity.by_telegram(int(user_ref))
        return user.id if user is not None else None
    try:
        return UUID(user_ref)
    except ValueError:
        return None
