"""Контракт модуля identity для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из identity только этот файл.
"""

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
    async def get_user(self, user_id: UserId) -> UserSummary | None: ...

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
