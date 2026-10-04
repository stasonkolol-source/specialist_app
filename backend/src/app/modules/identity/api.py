"""Контракт модуля identity для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из identity только этот файл.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.modules.identity.errors import AccountDeletedError as AccountDeletedError
from app.modules.identity.errors import ConsentRequiredError as ConsentRequiredError
from app.modules.identity.errors import InvalidRestrictionError as InvalidRestrictionError
from app.modules.identity.errors import UserNotFoundError as UserNotFoundError
from app.platform.contracts.events.identity import RestrictionKind as RestrictionKind
from app.platform.kernel.ids import CaseId, RestrictionId, UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Role as Role


class BlockSide(StrEnum):
    """Кто кого заблокировал (DEVELOPMENT_PLAN 4.7): правило блокировки действует в обе стороны,
    сторона нужна только для «Разблокировать» — снять блокировку может тот, кто её поставил."""

    BY_ME = "by_me"
    """Я заблокировал (если заблокировали оба — тоже это: свою блокировку можно снять)."""
    BY_THEM = "by_them"
    """Меня заблокировали."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockedUser:
    """Кого я заблокировал (S44): имя аккаунта и когда."""

    user_id: UserId
    display_name: str
    blocked_at: datetime


class Action(StrEnum):
    """Действие, которое проверяет единая точка «можно ли» (санкции и согласия)."""

    LOGIN = "login"
    POST = "post"
    RESPOND = "respond"
    MESSAGE = "message"


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSummary:
    id: UserId
    display_name: str
    ui_locale: Locale
    trust_level: int
    phone_verified: bool
    is_deleted: bool
    created_at: datetime
    block: BlockSide | None = None
    """Блокировка со зрителем — если его передали в `get_user` (4.7)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramUserView:
    """Пользователь, которого бот узнал по Telegram id (или только что создал /start)."""

    id: UserId
    display_name: str
    ui_locale: Locale
    trust_level: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RestrictionIn:
    """Санкция от модерации (2.5a): действует сразу, `ends_at` None — бессрочно."""

    user_id: UserId
    kind: RestrictionKind
    reason_code: str
    """Машинный код причины (`spam`, `prepayment_fraud`); текст решения — в модерации."""
    ends_at: datetime | None = None
    case_id: CaseId | None = None
    created_by: UserId | None = None


class IdentityApi(Protocol):
    async def get_user(
        self, user_id: UserId, *, viewer_id: UserId | None = None
    ) -> UserSummary | None:
        """Пользователь; с `viewer_id` — и блокировка между ними тем же запросом (4.7: карточка
        заявки S15 не тратит на неё отдельное чтение)."""
        ...

    async def users(
        self, user_ids: Collection[UserId], *, viewer_id: UserId | None = None
    ) -> dict[UserId, UserSummary]:
        """Пользователи пачкой (имена в списке диалогов S29); кого нет — нет и в ответе. С
        `viewer_id` — и блокировка с ним тем же запросом (отклики S23, 4.7)."""
        ...

    async def telegram_contacts(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        """«@username» сторон, которые показывают Telegram после договорённости (S43, 6.5): нет
        username, выключено или аккаунт удалён — нет в ответе. Вызывать, только когда стороны
        договорились."""
        ...

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        """Активный пользователь по Telegram id (бот). Telegram id в DTO не отдаём."""
        ...

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        """Личный чат пользователя с ботом — адрес канала доставки notifications (ADR-0011).

        В личном чате chat_id равен Telegram id. Только для адреса доставки: в логику и
        логи не попадает (ADR-0020 §14). None — пользователь удалён или вошёл не через
        Telegram.
        """
        ...

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        """Единая точка «можно ли» перед действием; чтение, вызывать до транзакции.

        RestrictedError (403 `restricted`) — действие запрещено действующей санкцией;
        ConsentRequiredError (403 `consent_required`) — создающее действие (всё, кроме
        LOGIN) до принятия действующих версий правил и политики.
        """
        ...

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        """Наложить санкцию в транзакции вызывающего (нужен активный UoW).

        Пишет identity.restrictions и событие UserRestricted; уровень доверия падает до 0
        (санкция — нарушение, ADR-0016 §2). InvalidRestrictionError — код причины не
        машинный или срок уже истёк; UserNotFoundError — нет пользователя.
        """
        ...

    async def roles(self, user_id: UserId) -> frozenset[Role]:
        """Роли персонала (identity.user_roles): кнопки чата модераторов и команды CLI."""
        ...

    async def lift_case_restrictions(self, case_id: CaseId) -> int:
        """Снять санкции, наложенные по кейсу (модератор одобрил то, что автопроверка
        заморозила), в транзакции вызывающего. Сколько снято."""
        ...

    async def record_violation(self, user_id: UserId) -> None:
        """Нарушение без санкции (предупреждение, подтверждённая жалоба) в транзакции
        вызывающего: уровень доверия — 0 на 14 дней. UserNotFoundError — нет пользователя."""
        ...

    async def hidden_from_search(
        self, user_ids: Collection[UserId]
    ) -> dict[UserId, datetime | None]:
        """Кого из пользователей не показывать в поиске (4.1): удалённых и тех, на ком
        действует приостановка, бан или теневой бан. Значение — когда человек снова станет
        виден (конец санкции); None — без срока. Остальных в ответе нет."""
        ...

    async def blocked_ids(self, user_id: UserId) -> frozenset[UserId]:
        """С кем у пользователя блокировка в любую сторону (4.7): кого он заблокировал и кто
        заблокировал его. Их не показывают ему выдача, лента и приглашения — и его им."""
        ...

    async def blocks_with(
        self, user_id: UserId, others: Collection[UserId]
    ) -> dict[UserId, BlockSide]:
        """Блокировки пользователя с `others` (4.7): переписка, отклик, приглашение — запрещены
        при любой стороне. Без блокировки — нет в ответе."""
        ...

    async def blocked_users(self, user_id: UserId) -> list[BlockedUser]:
        """Кого пользователь заблокировал (S44), недавние первыми."""
        ...


class DeletionHold(Protocol):
    """Legal hold удаления аккаунта (ARCHITECTURE §7.10): удаление ждёт решения открытых кейсов
    модерации о пользователе («жалобы удалим после их решения», S45), позже — и споров (6.1c).

    Реализует модуль выше по DAG (moderation): identity о нём не знает, связывает dishka — как
    media.api.LegalHold.
    """

    async def held(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        """Кого из пользователей удалять пока нельзя. Читает в транзакции вызывающего."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffMember:
    """Сотрудник в админке (2.7a): кто вошёл и с какими ролями (`identity.user_roles`)."""

    user_id: UserId
    login: str
    roles: frozenset[Role]


class StaffAuth(Protocol):
    """Вход персонала в админку (ADR-0009): пароль argon2 и код TOTP. Лимит неудачных попыток —
    у входного адаптера (interfaces/admin)."""

    async def authenticate(
        self, login: str, password: str, code: str, *, ip: str | None = None
    ) -> StaffMember | None:
        """Сотрудник — пароль и код TOTP верны, роль есть, аккаунт не удалён; иначе None (без
        причины: подбор не узнаёт, что именно не подошло). Вход пишется в audit_log."""
        ...

    async def member(self, user_id: UserId) -> StaffMember | None:
        """Сотрудник по id из сессии админки: роли перечитываются на каждый запрос, снятая роль
        или удалённый вход закрывают админку сразу."""
        ...
