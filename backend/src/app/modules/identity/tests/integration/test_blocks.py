"""Блокировки (DEVELOPMENT_PLAN 4.7): заблокировать и разблокировать, правило в обе стороны для
фасада, список S44, предел, удаление аккаунта стирает блокировки."""

from datetime import timedelta

import pytest

from app.modules.identity.api import BlockSide
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.block_user import BlockUserCommand
from app.modules.identity.application.use_cases.process_deletions import ProcessDeletionsCommand
from app.modules.identity.application.use_cases.request_deletion import RequestDeletionCommand
from app.modules.identity.application.use_cases.unblock_user import UnblockUserCommand
from app.modules.identity.domain.deletion import DeletionSource
from app.modules.identity.errors import (
    BlocksFullError,
    CannotBlockSelfError,
    UserNotFoundError,
)
from app.platform.kernel.ids import UserId, new_id

from .conftest import Identity, telegram_profile

pytestmark = pytest.mark.integration


async def sign_in(
    identity: Identity, first_name: str = "Ana", last_name: str = "Petrović"
) -> UserId:
    result = await identity.authenticate(
        AuthenticateTelegramCommand(
            profile=telegram_profile(
                id=812000000 + new_id().int % 100_000, first_name=first_name, last_name=last_name
            )
        )
    )
    return result.tokens.user_id


async def block(identity: Identity, actor: UserId, user: UserId) -> None:
    await identity.block_user(BlockUserCommand(actor_id=actor, user_id=user))


async def test_block_works_both_ways_and_unblock_only_lifts_my_side(identity: Identity) -> None:
    me, oleg = await sign_in(identity), await sign_in(identity, "Олег", "Р")
    marina = await sign_in(identity, "Марина", "Т")

    await block(identity, me, oleg)
    identity.clock.advance(timedelta(minutes=1))
    await block(identity, me, marina)
    await block(identity, me, marina)  # повтор — без ошибки
    await block(identity, oleg, me)

    facade = identity.facade
    assert await facade.blocked_ids(me) == {oleg, marina}
    assert await facade.blocked_ids(oleg) == {me}
    assert await facade.blocks_with(me, [oleg, marina]) == {
        oleg: BlockSide.BY_ME,  # заблокировали оба — своя главнее: её можно снять
        marina: BlockSide.BY_ME,
    }
    assert await facade.blocks_with(marina, [me, oleg]) == {me: BlockSide.BY_THEM}
    assert [user.user_id for user in await facade.blocked_users(me)] == [marina, oleg]

    await identity.unblock_user(UnblockUserCommand(actor_id=me, user_id=oleg))
    await identity.unblock_user(UnblockUserCommand(actor_id=me, user_id=oleg))  # повтор
    assert await facade.blocks_with(me, [oleg]) == {oleg: BlockSide.BY_THEM}
    assert [user.display_name for user in await facade.blocked_users(me)] == ["Марина Т"]


async def test_cannot_block_self_or_unknown(identity: Identity) -> None:
    me = await sign_in(identity)

    with pytest.raises(CannotBlockSelfError):
        await block(identity, me, me)
    with pytest.raises(UserNotFoundError):
        await block(identity, me, UserId(new_id()))


async def test_blocks_are_capped_but_a_repeat_still_passes(
    identity: Identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.modules.identity.application.use_cases.block_user.MAX_BLOCKS", 2)
    me = await sign_in(identity)
    first, second, third = await sign_in(identity), await sign_in(identity), await sign_in(identity)
    await block(identity, me, first)
    await block(identity, me, second)

    await block(identity, me, second)
    with pytest.raises(BlocksFullError):
        await block(identity, me, third)


async def test_account_deletion_forgets_blocks_both_ways(identity: Identity) -> None:
    me, other, third = await sign_in(identity), await sign_in(identity), await sign_in(identity)
    await block(identity, me, other)
    await block(identity, third, me)

    await identity.request_deletion(RequestDeletionCommand(actor_id=me, source=DeletionSource.TMA))
    identity.clock.advance(timedelta(days=7, minutes=1))
    report = await identity.process_deletions(ProcessDeletionsCommand())

    assert report.deleted == 1
    assert await identity.facade.blocked_ids(other) == frozenset()
    assert await identity.facade.blocked_ids(third) == frozenset()
