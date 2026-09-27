"""Вход через Telegram — общий для Mini App (initData) и бота (/start), ADR-0009.

Один и тот же код находит пользователя по `auth_identities(telegram, <id>)` или
регистрирует нового; у существующего проверяет санкции входа и обновляет снимок профиля.
"""

from datetime import datetime

from app.modules.identity.api import Action
from app.modules.identity.application.access import ensure_allowed
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import IdentityQuery, UserRepository
from app.modules.identity.domain.user import (
    AuthProvider,
    User,
    clean_display_name,
    locale_from_language,
)


async def sign_in_telegram(
    users: UserRepository, query: IdentityQuery, profile: TelegramProfile, now: datetime
) -> tuple[User, bool]:
    """(пользователь, создан ли сейчас). Нужен активный UoW вызывающего."""
    subject = str(profile.id)
    user = await users.find_by_identity(AuthProvider.TELEGRAM, subject)
    if user is None:
        user = User.register(
            provider=AuthProvider.TELEGRAM,
            subject=subject,
            profile=profile.snapshot(),
            display_name=clean_display_name(profile.first_name, profile.last_name),
            ui_locale=locale_from_language(profile.language_code),
            now=now,
        )
        await users.add(user)
        return user, True
    ensure_allowed(await query.restrictions(user.id, now), Action.LOGIN, now)
    user.record_login(
        provider=AuthProvider.TELEGRAM, subject=subject, profile=profile.snapshot(), now=now
    )
    await users.save(user)
    return user, False
