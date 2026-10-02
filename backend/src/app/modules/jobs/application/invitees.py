"""Кого можно пригласить в заявку или кому отправить прямой запрос (DEVELOPMENT_PLAN 5.6):
опубликованный профиль, автор не под санкцией и не сам клиент."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.identity.api import IdentityApi
from app.modules.jobs.errors import InviteeNotFoundError, OwnProfileInviteError
from app.modules.specialists.api import PublicProfile, SpecialistsApi
from app.platform.kernel.ids import UserId


async def invitees(
    specialists: SpecialistsApi,
    identity: IdentityApi,
    actor_id: UserId,
    profile_ids: Sequence[UUID],
) -> list[PublicProfile]:
    """Опубликованные профили, чьи авторы не под санкцией и не сам клиент; иначе — ошибка с
    первым неподходящим. Читает до транзакции."""
    profiles = []
    for profile_id in profile_ids:
        profile = await specialists.public_profile(profile_id)
        if profile is None:
            raise InviteeNotFoundError(profile_id=profile_id)
        if profile.user_id == actor_id:
            raise OwnProfileInviteError(profile_id=profile_id)
        profiles.append(profile)
    hidden = await identity.hidden_from_search([profile.user_id for profile in profiles])
    for profile in profiles:
        if profile.user_id in hidden:
            raise InviteeNotFoundError(profile_id=profile.id)
    return profiles
