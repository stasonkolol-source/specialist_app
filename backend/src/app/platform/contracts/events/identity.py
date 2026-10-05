"""События модуля identity (ADR-0020 §2).

`RestrictionKind` — часть published language: вид санкции ставит модерация через фасад
identity, а подписчики (уведомления, модерация) получают его в `UserRestricted`.
`EntryPoint` — тоже: где пользователь вошёл впервые, для атрибуции в growth.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CaseId, CityId, RestrictionId, UserId


class RestrictionKind(StrEnum):
    """Вид санкции в identity.restrictions (ADR-0009, ADR-0016)."""

    LIMITED = "limited"
    """Лимиты новичка (страйк 1, ADR-0016 §4): действий не запрещает — антиспам-лимиты
    считаются как для уровня доверия 0–1, а уровень доверия не выше 0."""
    POSTING_BLOCKED = "posting_blocked"
    RESPONDING_BLOCKED = "responding_blocked"
    MESSAGING_BLOCKED = "messaging_blocked"
    SHADOW_BANNED = "shadow_banned"
    SUSPENDED = "suspended"
    BANNED = "banned"


class EntryPoint(StrEnum):
    """Где пользователь вошёл через Telegram."""

    MINI_APP = "mini_app"
    """Mini App: initData, `start_param` — код `startapp`."""
    BOT = "bot"
    """Личный чат с ботом: `/start <payload>`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegistered(DomainEvent):
    """Новый аккаунт: первый вход через провайдера `provider` (сейчас — telegram).

    `entry_point` и `start_param` — первое касание для атрибуции (growth, 1.4b):
    `start_param` — сырой код `startapp` из проверенного initData или payload `/start`.
    identity пропускает только синтаксис Telegram (до 64 символов `[A-Za-z0-9_-]`), тип
    ссылки и суффикс `_r` разбирает кодек growth. Поля добавлены аддитивно: у событий,
    поставленных до 1.4b, их нет.

    `reregistered` — тот же Telegram-аккаунт удалял аккаунт в последние 12 месяцев (хэш в
    `deleted_identity_hashes`, 2.12): модерация пишет сигнал риска, данные не возвращаются.
    `had_sanctions` — у удалённого аккаунта были санкции. Поля аддитивные, с 2.12.
    """

    event_type = "identity.UserRegistered"
    user_id: UserId
    provider: str
    entry_point: EntryPoint | None = None
    start_param: str | None = None
    reregistered: bool = False
    had_sanctions: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class BotStarted(DomainEvent):
    """Пользователь отправил боту `/start` в личном чате (и новый, и вернувшийся).

    С этого момента Telegram разрешает боту писать ему первым (ADR-0011). Подписчик —
    notifications: канал `telegram` становится доступным для доставки. identity ниже
    notifications по DAG и не вызывает его фасад, поэтому связь — только событием.
    """

    event_type = "identity.BotStarted"
    user_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UserUpdated(DomainEvent):
    """Изменился профиль пользователя: проекции обновляют копии нужных им полей.

    `fields` — имена изменённых полей (`display_name`, `ui_locale`, `home_city_id`,
    `intent`, `trust_level`): подписчик пропускает событие, если его поля не менялись.
    """

    event_type = "identity.UserUpdated"
    user_id: UserId
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRestricted(DomainEvent):
    """На пользователя наложена санкция (identity.restrictions).

    `until` — до когда; None — бессрочно. `case_id` — кейс модерации, если он есть.
    Подписчики: уведомление `account.restricted` (2.3), отзыв сессий при приостановке и
    бане (2.5a).
    """

    event_type = "identity.UserRestricted"
    user_id: UserId
    restriction_id: RestrictionId
    kind: RestrictionKind
    reason_code: str
    until: datetime | None
    case_id: CaseId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRestrictionsLifted(DomainEvent):
    """Санкции пользователя сняты досрочно: модератор одобрил то, что автопроверка заморозила
    (кейс), позже — снятие в админке. Подписчик — поиск (4.1): профиль снова в выдаче, если
    других скрывающих санкций нет. Санкция, истёкшая по сроку, события не даёт — её конец
    подписчик знает заранее из `UserRestricted.until`."""

    event_type = "identity.UserRestrictionsLifted"
    user_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class OnboardingCompleted(DomainEvent):
    """Пользователь впервые принял правила площадки и политику (S02c) — онбординг пройден.

    Публикуется один раз на пользователя: повторное согласие с новой редакцией — не
    онбординг. `intent` (`client`, `pro`, `casual`) и `home_city_id` — что выбрано на S02b и
    S02a; None — если шаг пропустили (API это позволяет). Подписчик — аналитика (1.7).
    """

    event_type = "identity.OnboardingCompleted"
    user_id: UserId
    intent: str | None
    home_city_id: CityId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class UserDeleted(DomainEvent):
    """Аккаунт удалён по запросу после grace-периода (ARCHITECTURE §7.10, 2.12).

    identity уже обезличил пользователя: имя «Удалённый пользователь», способов входа и
    телефона нет. Подписчики удаляют или обезличивают своё: профиль исполнителя и прайс,
    файлы, каналы и ленту уведомлений, атрибуцию. Модуль с персональными данными, который
    появится позже, подписывается в своём шаге (правило DoD). Записи, которые закон требует
    хранить (согласия, решения модерации), остаются с тем же `user_id` — он ничего не говорит
    о человеке.
    """

    event_type = "identity.UserDeleted"
    user_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UserBlocked(DomainEvent):
    """`blocker_id` заблокировал `blocked_id` (PUT /me/blocks; DEVELOPMENT_PLAN 4.7).

    Блокировка действует в обе стороны: друг друга они больше не видят. Подписчик — jobs:
    отклики одного на открытые заявки другого перестают занимать места (MU-3). Заблокированному
    ничего не сообщают. Повтор той же блокировки события не даёт.
    """

    event_type = "identity.UserBlocked"
    blocker_id: UserId
    blocked_id: UserId
