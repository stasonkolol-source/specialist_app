"""Заблокировать пользователя (PUT /me/blocks/{user_id}; меню S08 и S30, «Также заблокировать» на
S46; DEVELOPMENT_PLAN 4.7).

Блокировка действует сразу и в обе стороны: переписка, отклики на заявки и приглашения между
двумя запрещены, выдача, лента и приглашения не показывают их друг другу. Повтор — без ошибки.
Себя — 409 `cannot_block_self`; удалённого или неизвестного — 404; больше MAX_BLOCKS — 409
`blocks_full` (повтор уже заблокированного проходит и на пределе).
"""

from dataclasses import dataclass

from app.modules.identity.api import BlockSide
from app.modules.identity.application.ports import Blocks, IdentityQuery
from app.modules.identity.domain.blocks import MAX_BLOCKS
from app.modules.identity.errors import BlocksFullError, CannotBlockSelfError, UserNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockUserCommand:
    actor_id: UserId
    user_id: UserId


class BlockUser:
    def __init__(self, uow: UnitOfWork, blocks: Blocks, query: IdentityQuery, clock: Clock) -> None:
        self._uow, self._blocks, self._query, self._clock = uow, blocks, query, clock

    async def __call__(self, cmd: BlockUserCommand) -> None:
        if cmd.user_id == cmd.actor_id:
            raise CannotBlockSelfError
        target = await self._query.user_summary(cmd.user_id)
        if target is None or target.is_deleted:
            raise UserNotFoundError(user_id=cmd.user_id)
        async with self._uow:
            if await self._blocks.count(cmd.actor_id) >= MAX_BLOCKS:
                sides = await self._blocks.sides(cmd.actor_id, [cmd.user_id])
                if sides.get(cmd.user_id) is BlockSide.BY_ME:
                    return
                raise BlocksFullError(limit=MAX_BLOCKS)
            await self._blocks.add(cmd.actor_id, cmd.user_id, now=self._clock.now())
