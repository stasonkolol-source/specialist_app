"""Вход через Telegram — общий для Mini App (initData) и бота (/start), ADR-0009.

Один и тот же код находит пользователя по `auth_identities(telegram, <id>)` или
регистрирует нового; у существующего проверяет санкции входа и обновляет снимок профиля.
Код deep link (`startapp` или payload `/start`) попадает в `UserRegistered` для
атрибуции первого касания (growth); вернувшемуся пользователю он не нужен.

Удалённый аккаунт способов входа не хранит: тот же Telegram регистрирует новый. Хэш его ID
за последние 12 месяцев (§7.10) отмечает регистрацию повторной — модерация пишет сигнал
риска, данные прежнего аккаунта не возвращаются.
"""

import re
from datetime import datetime
from typing import Final

from app.modules.identity.api import Action
from app.modules.identity.application.access import ensure_allowed
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import (
    DeletedIdentities,
    IdentityQuery,
    UserRepository,
)
from app.modules.identity.domain.deletion import HashKind, identity_hash
from app.modules.identity.domain.user import (
    AuthProvider,
    User,
    clean_display_name,
    locale_from_language,
)
from app.platform.contracts.events.identity import EntryPoint

START_PARAM_MAX_LENGTH: Final = 64
_START_PARAM: Final = re.compile(r"[A-Za-z0-9_-]+")


def telegram_start_param(raw: str | None) -> str | None:
    """Код deep link в синтаксисе Telegram: до 64 символов `[A-Za-z0-9_-]`.

    Такой код дают только ссылки `startapp=` и `start=`. Текст, набранный после /start
    руками, — не ссылка: его не храним (там могут быть личные данные).
    """
    if raw is None or len(raw) > START_PARAM_MAX_LENGTH or not _START_PARAM.fullmatch(raw):
        return None
    return raw


async def sign_in_telegram(
    users: UserRepository,
    query: IdentityQuery,
    deleted: DeletedIdentities,
    profile: TelegramProfile,
    now: datetime,
    *,
    hash_key: bytes,
    entry_point: EntryPoint,
    start_param: str | None = None,
) -> tuple[User, bool]:
    """(пользователь, создан ли сейчас). Нужен активный UoW вызывающего."""
    subject = str(profile.id)
    user = await users.find_by_identity(AuthProvider.TELEGRAM, subject)
    if user is None:
        had_sanctions = await deleted.find(identity_hash(hash_key, HashKind.TELEGRAM, subject), now)
        user = User.register(
            provider=AuthProvider.TELEGRAM,
            subject=subject,
            profile=profile.snapshot(),
            display_name=clean_display_name(profile.first_name, profile.last_name),
            ui_locale=locale_from_language(profile.language_code),
            now=now,
            entry_point=entry_point,
            start_param=telegram_start_param(start_param),
            reregistered=had_sanctions is not None,
            had_sanctions=bool(had_sanctions),
        )
        await users.add(user)
        return user, True
    ensure_allowed(await query.restrictions(user.id, now), Action.LOGIN, now)
    user.record_login(
        provider=AuthProvider.TELEGRAM, subject=subject, profile=profile.snapshot(), now=now
    )
    await users.save(user)
    return user, False
