"""Отклик по id (GET /responses/{id}): исполнителю — свой, с заявкой (форма правки S16); владельцу
заявки — отклик, который он видит в S23 и S24: прошедший проверку, без блокировки между ними (4.7).
Контракт — «исполнитель или владелец»; владелец раньше получал 404 (owner-404). Остальным — как
несуществующий: 404. Редакция отклика — его ETag: её клиент передаёт в If-Match при выборе
(ADV-08)."""

from dataclasses import dataclass

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.responses import MyResponse
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.errors import ResponseNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowResponseCommand:
    actor_id: UserId
    response_id: ResponseId


class ShowResponse:
    def __init__(self, queries: JobQueries, identity: IdentityApi) -> None:
        self._queries, self._identity = queries, identity

    async def __call__(self, cmd: ShowResponseCommand) -> MyResponse:
        mine = await self._queries.my_response(cmd.actor_id, cmd.response_id)
        if mine is not None:
            return mine
        owned = await self._queries.owner_response(cmd.actor_id, cmd.response_id)
        if owned is None or await self._identity.blocks_with(cmd.actor_id, [owned.performer_id]):
            raise ResponseNotFoundError(response_id=cmd.response_id)
        return owned
