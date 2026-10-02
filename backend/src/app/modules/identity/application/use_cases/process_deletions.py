"""Исполнить запросы на удаление, чей срок пришёл (periodic `identity.process_deletions`,
ежечасно; ARCHITECTURE §7.10).

Каждый аккаунт — своя транзакция: сбой одного не мешает остальным. Открыт кейс модерации о
пользователе — удаление ждёт решения (DeletionHold): запрос остаётся, следующий запуск
проверит снова. В транзакции:
1. хэши Telegram ID и телефона — антифрод на 12 месяцев (повторная регистрация — сигнал риска);
2. `User.forget` — обезличен, без способов входа; событие UserDeleted подписчикам — профиль,
   прайс, файлы, уведомления, атрибуция;
3. сессии удалены (в них IP и устройство), живые — сначала в denylist Valkey: access-токен
   действует ещё до 15 минут;
4. запрос исполнен.
"""

from dataclasses import dataclass
from typing import Final

import structlog

from app.modules.identity.api import DeletionHold
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.ports import (
    DeletedIdentities,
    DeletionRepository,
    DueCursor,
    SessionRepository,
    SessionRevocations,
    UserRepository,
)
from app.modules.identity.domain.deletion import HASH_RETENTION, login_hashes
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

log = structlog.get_logger(__name__)

BATCH: Final = 100
"""Страница очереди: запуск проходит её всю, страницами, — удержанные (legal hold) не
заслоняют остальных."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessDeletionsCommand:
    limit: int = BATCH


@dataclass(frozen=True, slots=True, kw_only=True)
class DeletionsReport:
    deleted: int
    held: int


class ProcessDeletions:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        deletions: DeletionRepository,
        sessions: SessionRepository,
        revocations: SessionRevocations,
        hashes: DeletedIdentities,
        hold: DeletionHold,
        config: IdentityConfig,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._deletions = uow, users, deletions
        self._sessions, self._revocations, self._hashes = sessions, revocations, hashes
        self._hold, self._config, self._clock = hold, config, clock

    async def __call__(self, cmd: ProcessDeletionsCommand) -> DeletionsReport:
        now = self._clock.now()
        deleted = held = 0
        cursor: DueCursor | None = None
        while True:
            page = await self._deletions.due(now, after=cursor, limit=cmd.limit)
            for _, user_id in page:
                outcome = await self._process(user_id)
                deleted += outcome == "deleted"
                held += outcome == "held"
            if len(page) < cmd.limit:
                break
            cursor = page[-1]
        if deleted or held:
            log.info("account_deletions_processed", deleted=deleted, held=held)
        return DeletionsReport(deleted=deleted, held=held)

    async def _process(self, user_id: UserId) -> str:
        now = self._clock.now()
        async with self._uow:
            # порядок блокировок — как у RequestDeletion: пользователь, затем запрос
            user = await self._users.get_for_update(user_id)
            request = await self._deletions.active_for_update(user_id)
            if request is None or not request.due(now):
                return "skipped"  # отменили или исполнил параллельный запуск
            if user_id in await self._hold.held([user_id]):
                return "held"
            if user.status is not UserStatus.DELETED:
                telegram = [
                    identity.subject
                    for identity in user.identities
                    if identity.provider is AuthProvider.TELEGRAM
                ]
                await self._hashes.remember(
                    login_hashes(
                        self._config.hash_key, telegram_ids=telegram, phone=user.phone_e164
                    ),
                    # нарушения — санкции и подтверждённые жалобы (2.5a): учтёт сигнал риска
                    had_sanctions=user.trust_penalty_at is not None,
                    deleted_at=now,
                    purge_after=now + HASH_RETENTION,
                )
                user.forget(now=now)
                await self._users.save(user)
            for session in await self._sessions.active_for_user(user_id, now):
                await self._revocations.revoke(session.sid)
            await self._sessions.forget_user(user_id)
            request.complete(now=now)
            await self._deletions.save(request)
        return "deleted"
