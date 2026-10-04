"""Порты модуля notifications (ADR-0020 §3, §5)."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from app.modules.notifications.application.dto import (
    BroadcastContent,
    BroadcastStats,
    BroadcastSummary,
    ChannelView,
    DeliveryTarget,
    NewNotification,
    NotificationRecord,
    RenderedText,
    TelegramTarget,
)
from app.modules.notifications.domain.broadcast import Broadcast, BroadcastId, Segment
from app.modules.notifications.domain.catalog import EventGroup, NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import (
    DeliveryId,
    DeliveryStatus,
    NotificationId,
)
from app.modules.notifications.domain.settings import NotificationSettings
from app.platform.contracts.events.deals import (
    DealCancelled,
    DealCompletionDue,
    DealDisputed,
    DealMarkedDone,
    DealProposed,
    DealReminderDue,
    DisputeResolved,
)
from app.platform.contracts.events.identity import BotStarted, UserDeleted, UserRestricted
from app.platform.contracts.events.jobs import (
    JobClosed,
    JobExpired,
    JobExpiring,
    JobInvited,
    ResponseAccepted,
    ResponseSubmitted,
)
from app.platform.contracts.events.messaging import MessageSent
from app.platform.contracts.events.moderation import AppealDecided, ModerationDecisionMade
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRequested
from app.platform.contracts.events.specialists import ProfilePublished, ProfileStale
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef
from app.platform.telegram.port import ButtonLine


class ChannelRepository(Protocol):
    """Каналы доставки — простая запись (ADR-0020 §5)."""

    async def grant_telegram(
        self, user_id: UserId, chat_id: int, *, via: GrantedVia, now: datetime
    ) -> tuple[ChannelView, bool]:
        """Канал telegram доступен: создать или включить выключенный.

        Уже доступный канал не меняется — повтор идемпотентен. Второе значение — стал ли
        канал доступным сейчас (создан или включён): False у повтора. Нужен активный UoW.
        """
        ...

    async def telegram_target(self, user_id: UserId) -> TelegramTarget | None:
        """Канал telegram пользователя; None — боту писать не разрешали. Нужен активный UoW."""
        ...

    async def disable(self, channel_id: UUID, *, at: datetime) -> bool:
        """Бот заблокирован (403 на отправку в `at`): канал выключен. False — уже выключен
        или разрешение новее `at` (человек снова нажал /start). Нужен активный UoW."""
        ...

    async def disable_telegram(self, user_id: UserId, *, at: datetime) -> bool:
        """То же по пользователю (`my_chat_member` → kicked в `at`)."""
        ...


class NotificationRepository(Protocol):
    """Уведомления и доставки — простые записи (ADR-0020 §5). Нужен активный UoW."""

    async def add(self, notification: NewNotification) -> NotificationId | None:
        """Записать уведомление; None — `dedupe_key` уже был (повтор события)."""
        ...

    async def add_delivery(
        self, notification_id: NotificationId, channel_id: UUID, *, not_before: datetime
    ) -> DeliveryId:
        """Доставка в канал в статусе `queued`."""
        ...

    async def record_failure(self, delivery_id: DeliveryId, *, error: str) -> int | None:
        """Попытка не удалась (сеть, 5xx): сколько их уже; None — доставка не `queued`."""
        ...

    async def expire_stale(self, *, due_before: datetime, limit: int) -> int:
        """До `limit` доставок `queued` со сроком раньше `due_before` → `failed` (`stale`)."""
        ...

    async def postpone_delivery(self, delivery_id: DeliveryId, *, not_before: datetime) -> bool:
        """Сдвинуть `not_before` доставки в `queued`; False — уже не `queued`."""
        ...

    async def settle_delivery(
        self,
        delivery_id: DeliveryId,
        status: DeliveryStatus,
        *,
        now: datetime,
        provider_message_id: str | None = None,
        error: str | None = None,
        attempt: bool = True,
    ) -> bool:
        """`queued` → итог; False — доставка уже не `queued` (повтор задачи). `attempt` —
        засчитать попытку (False — её уже записал record_failure)."""
        ...

    async def mark_read(
        self, user_id: UserId, ids: Collection[NotificationId] | None, *, now: datetime
    ) -> int:
        """Отметить прочитанными свои уведомления центра (None — все); сколько отмечено."""
        ...

    async def suppress_queued(self, dedupe_prefix: str, *, error: str, now: datetime) -> int:
        """Доставки `queued` уведомлений с ключом на `dedupe_prefix` → `suppressed` (карточки
        закрытой заявки, которые ждали конца тихих часов); сколько."""
        ...


class SettingsRepository(Protocol):
    """Настройки уведомлений — простая запись. Нужен активный UoW."""

    async def load(self, user_id: UserId) -> NotificationSettings: ...

    async def lock(self, user_id: UserId) -> None:
        """Настройки пользователя заняты до конца транзакции: переключения из бота идут по
        одному, и двойное нажатие не теряет второе."""
        ...

    async def save(self, user_id: UserId, settings: NotificationSettings) -> None:
        """Заменить выбор «группа × канал», тихие часы и час дайджеста."""
        ...


class NotificationQuery(Protocol):
    """Чтение без блокировок (ADR-0020 §4)."""

    async def page(self, user_id: UserId, request: PageRequest) -> Page[NotificationRecord]:
        """Центр уведомлений: новые сверху, курсор по id (UUIDv7)."""
        ...

    async def unread(self, user_id: UserId) -> int: ...

    async def delivery(self, delivery_id: DeliveryId) -> DeliveryTarget | None: ...

    async def deliveries_of(self, notification_id: NotificationId) -> list[DeliveryId]:
        """Доставки уведомления (`cli notify-test` отправляет их сразу)."""
        ...

    async def settings(self, user_id: UserId) -> NotificationSettings: ...

    async def telegram_channel(self, user_id: UserId) -> ChannelView | None: ...

    async def sent_with_prefix(self, dedupe_prefix: str) -> list[DeliveryId]:
        """Отправленные в бот доставки уведомлений с ключом на `dedupe_prefix` (карточки B1
        заявки: `job.matched:<заявка>:`) — у них есть id сообщения для правки кнопок."""
        ...

    async def digest_hours(self, user_ids: Collection[UserId]) -> dict[UserId, int]:
        """Час дайджеста тех, кто его менял; остальных нет в ответе (умолчание — 09:00)."""
        ...


class NotificationRenderer(Protocol):
    """Текст уведомления по шаблонам gettext на языке читателя (ADR-0013)."""

    def renders(self, type_: NotificationType) -> bool:
        """Есть ли у типа шаблоны: без них уведомление не создаётся."""
        ...

    def text(
        self, type_: NotificationType, params: Mapping[str, str], locale: Locale
    ) -> RenderedText:
        """Заголовок и текст центра уведомлений — простой текст."""
        ...

    def telegram(
        self,
        type_: NotificationType,
        params: Mapping[str, str],
        link: str | None,
        locale: Locale,
    ) -> tuple[str, tuple[ButtonLine, ...]]:
        """HTML сообщения бота и его кнопки: web_app с кодом deep link или callback."""
        ...

    def retired_buttons(
        self,
        type_: NotificationType,
        params: Mapping[str, str],
        link: str | None,
        locale: Locale,
    ) -> tuple[ButtonLine, ...]:
        """Кнопки уже отправленной карточки, когда её действия больше не работают (заявку
        закрыли, 5.7)."""
        ...

    def broadcast(
        self, content: BroadcastContent, locale: Locale
    ) -> tuple[str, tuple[ButtonLine, ...]]:
        """Сообщение рассылки (2.7b): текст админки на языке читателя — простым текстом, без
        разметки; кнопка «Открыть» с кодом deep link или «Хочу узнать первым» (Q24)."""
        ...


class BroadcastRepository(Protocol):
    """Рассылки — агрегат с версией (2.7b). Нужен активный UoW."""

    async def add(self, broadcast: Broadcast) -> None: ...

    async def get_for_update(self, broadcast_id: BroadcastId) -> Broadcast:
        """Строка рассылки заблокирована до конца транзакции: отмена и пачка разбора аудитории
        идут по одной. Нет такой — BroadcastNotFoundError."""
        ...

    async def save(self, broadcast: Broadcast) -> None: ...


class BroadcastQuery(Protocol):
    """Чтение рассылок без блокировок (ADR-0020 §4)."""

    async def content(self, broadcast_id: BroadcastId) -> BroadcastContent | None: ...

    async def stats(self, broadcast_id: BroadcastId) -> BroadcastStats:
        """Счётчики по доставкам уведомлений рассылки (ключ `broadcast:<id>:`)."""
        ...

    async def pending(self, broadcast_id: BroadcastId) -> int:
        """Сколько доставок рассылки ещё ждут отправки."""
        ...

    async def recent(self, page: PageRequest) -> Page[BroadcastSummary]:
        """Рассылки, новые первыми (Admin API). InvalidCursorError — курсор битый."""
        ...

    async def summary(self, broadcast_id: BroadcastId) -> BroadcastSummary | None: ...


class AudienceSource(Protocol):
    """Кандидаты в получатели рассылки (2.7b): у кого боту можно писать и группа включена."""

    async def candidates(
        self, group: EventGroup, *, after: UserId | None, limit: int
    ) -> list[UserId]:
        """До `limit` пользователей по возрастанию id после `after`: канал telegram доступен,
        группа включена в боте (opt-in — только явным выбором)."""
        ...

    async def segments(self, user_ids: Collection[UserId]) -> dict[UserId, Segment]:
        """Профиль исполнителя и город кандидатов (фасады identity и specialists); удалённых
        аккаунтов нет в ответе."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SendDeliveryPayload:
    delivery_id: UUID


class RecipientData(Protocol):
    """Всё, что модуль хранит о получателе, — для удаления аккаунта (§7.10)."""

    async def forget(self, user_id: UserId) -> None:
        """Удалить ленту, доставки, каналы, предпочтения и настройки получателя."""
        ...


GRANT_WRITE_ACCESS: Final = TaskRef("notifications.grant_write_access", BotStarted)
"""Подписчик BotStarted: /start разрешает боту писать — канал telegram доступен."""

SEND_DELIVERY: Final = TaskRef("notifications.send", SendDeliveryPayload, queue="notifications")
"""Отправить доставку в канал (не раньше `not_before`)."""

NOTIFY_ACCOUNT_RESTRICTED: Final = TaskRef(
    "notifications.notify_account_restricted", UserRestricted, queue="notifications"
)
NOTIFY_PROFILE_PUBLISHED: Final = TaskRef(
    "notifications.notify_profile_published", ProfilePublished, queue="notifications"
)
NOTIFY_MODERATION_DECISION: Final = TaskRef(
    "notifications.notify_moderation_decision", ModerationDecisionMade, queue="notifications"
)
NOTIFY_APPEAL_DECIDED: Final = TaskRef(
    "notifications.notify_appeal_decided", AppealDecided, queue="notifications"
)
NOTIFY_JOB_EXPIRING: Final = TaskRef(
    "notifications.notify_job_expiring", JobExpiring, queue="notifications"
)
NOTIFY_JOB_EXPIRED: Final = TaskRef(
    "notifications.notify_job_expired", JobExpired, queue="notifications"
)
RESPONSES_DEBOUNCE: Final = timedelta(minutes=5)
"""Окно дебаунса `response.received` (§11.3): отклики за пять минут — одно уведомление."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponsesWindow:
    """Окно откликов на заявку: уведомление клиенту — в его конце."""

    job_id: UUID
    since: datetime
    """Первый отклик окна: окно — ключ дедупликации уведомления."""


SCHEDULE_RESPONSES_NOTICE: Final = TaskRef(
    "notifications.schedule_responses_notice", ResponseSubmitted, queue="notifications"
)
"""Подписчик ResponseSubmitted: первый отклик окна ставит уведомление через RESPONSES_DEBOUNCE,
следующие, пока оно ждёт, — ничего (замок очереди по заявке)."""
NOTIFY_RESPONSES: Final = TaskRef(
    "notifications.notify_responses", ResponsesWindow, queue="notifications"
)
"""Конец окна: «Новых откликов: 3» по видимым клиенту и ещё не открытым откликам."""

MESSAGES_DEBOUNCE: Final = timedelta(minutes=1)
"""Окно дебаунса `message.received` (6.3b): серия сообщений за минуту — одно уведомление."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagesWindow:
    """Окно сообщений диалога для одного получателя: уведомление — в его конце."""

    conversation_id: UUID
    recipient_id: UserId
    since: datetime
    """Первое сообщение окна: окно — ключ дедупликации уведомления."""


SCHEDULE_MESSAGES_NOTICE: Final = TaskRef(
    "notifications.schedule_messages_notice", MessageSent, queue="notifications"
)
"""Подписчик MessageSent: первое сообщение окна ставит уведомление получателю через
MESSAGES_DEBOUNCE, следующие, пока оно ждёт, — ничего (замок очереди по диалогу и получателю)."""
NOTIFY_MESSAGES: Final = TaskRef(
    "notifications.notify_messages", MessagesWindow, queue="notifications"
)
"""Конец окна: «Алексей пишет» с началом последнего сообщения, если получатель ещё не прочитал
и не смотрит диалог прямо сейчас."""

NOTIFY_JOB_INVITED: Final = TaskRef(
    "notifications.notify_job_invited", JobInvited, queue="notifications"
)
"""Подписчик JobInvited (5.6): специалисту — «Вас пригласили» или «Прямой запрос» с «Посмотреть
заявку» и кнопками его шаблонов."""

NOTIFY_RESPONSE_ACCEPTED: Final = TaskRef(
    "notifications.notify_response_accepted", ResponseAccepted, queue="notifications"
)
"""Подписчик ResponseAccepted (6.1b): выбранному исполнителю — «Клиент выбрал вас» и кнопка
к сделке; адрес в сообщение не кладём — он внутри сделки."""
NOTIFY_PASSED_OVER: Final = TaskRef(
    "notifications.notify_passed_over", ResponseAccepted, queue="notifications"
)
"""Подписчик ResponseAccepted: остальным откликнувшимся — «Клиент выбрал другого исполнителя»."""
NOTIFY_DEAL_PROPOSED: Final = TaskRef(
    "notifications.notify_deal_proposed", DealProposed, queue="notifications"
)
"""Подписчик DealProposed: второй стороне — «предлагает договориться», подтвердить за 72 ч."""
NOTIFY_DEAL_CANCELLED: Final = TaskRef(
    "notifications.notify_deal_cancelled", DealCancelled, queue="notifications"
)
"""Подписчик DealCancelled: второй стороне — кто отменил и почему; клиенту из отклика — «заявка
снова открыта»."""
NOTIFY_DEAL_REMINDER: Final = TaskRef(
    "notifications.notify_deal_reminder", DealReminderDue, queue="notifications"
)
"""Подписчик DealReminderDue: обеим сторонам — напоминание за 2 ч до времени сделки."""
NOTIFY_DEAL_COMPLETION: Final = TaskRef(
    "notifications.notify_deal_completion", DealCompletionDue, queue="notifications"
)
"""Подписчик DealCompletionDue: «Работа выполнена?» с [Да, всё хорошо] и [Есть проблема] тем,
кто ещё не отметил."""
NOTIFY_DEAL_MARKED: Final = TaskRef(
    "notifications.notify_deal_marked", DealMarkedDone, queue="notifications"
)
"""Подписчик DealMarkedDone: второй стороне — «Работа выполнена?» сразу (B2, 7.3): «исполнитель
(клиент) отметил работу выполненной. Всё в порядке?»."""

NOTIFY_DISPUTE_OPENED: Final = TaskRef(
    "notifications.notify_dispute_opened", DealDisputed, queue="notifications"
)
"""Подписчик DealDisputed: второй стороне — «сообщил о проблеме», 48 ч на ответ и «Ответить»
(S52, 6.1c), пока спор ждёт ответа."""
NOTIFY_DISPUTE_RESOLVED: Final = TaskRef(
    "notifications.notify_dispute_resolved", DisputeResolved, queue="notifications"
)
"""Подписчик DisputeResolved: обеим сторонам — решение поддержки по спору и причина (statement
of reasons, 6.1c)."""

NOTIFY_REVIEW_REQUEST: Final = TaskRef(
    "notifications.notify_review_request", ReviewRequested, queue="notifications"
)
"""Подписчик ReviewRequested: клиенту — «Как прошла работа?» и «Оставить отзыв» (7.2), пока
отзыва нет и окно открыто."""
NOTIFY_REVIEW_PUBLISHED: Final = TaskRef(
    "notifications.notify_review_published", ReviewPublished, queue="notifications"
)
"""Подписчик ReviewPublished: исполнителю — новый отзыв и «Ответить на отзыв» (7.2)."""

NOTIFY_PROFILE_STALE: Final = TaskRef(
    "notifications.notify_profile_stale", ProfileStale, queue="notifications"
)
"""Подписчик ProfileStale (5.7): специалисту — «Включить «Доступен сегодня»» или «Обновить
профиль», не чаще раза в 2 недели (решает specialists)."""

RETIRE_CLOSED_CARDS: Final = TaskRef(
    "notifications.retire_closed_cards", JobClosed, queue="notifications"
)
RETIRE_EXPIRED_CARDS: Final = TaskRef(
    "notifications.retire_expired_cards", JobExpired, queue="notifications"
)
RETIRE_ASSIGNED_CARDS: Final = TaskRef(
    "notifications.retire_assigned_cards", ResponseAccepted, queue="notifications"
)
"""Заявка закрыта, истекла или клиент выбрал исполнителя (5.7): карточки B1 гасят кнопки, ждущие
тихих часов — не уходят."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RetireCardPayload:
    delivery_id: UUID


RETIRE_CARD: Final = TaskRef("notifications.retire_card", RetireCardPayload, queue="notifications")
"""Одна карточка B1: правка кнопок — вызов Bot API под лимитером, как отправка."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BroadcastPayload:
    broadcast_id: UUID


FAN_OUT_BROADCAST: Final = TaskRef(
    "notifications.fan_out_broadcast", BroadcastPayload, queue="notifications"
)
"""Пачка получателей рассылки: уведомления, доставки и задачи отправки; следующая пачка —
следующей задачей. Приоритет — как у отправки рассылки (P4)."""
FINISH_BROADCAST: Final = TaskRef(
    "notifications.finish_broadcast", BroadcastPayload, queue="notifications"
)
"""Аудитория разобрана: рассылка завершается, когда не останется ждущих доставок (проверка
раз в BROADCAST_POLL)."""
BROADCAST_POLL: Final = timedelta(minutes=1)

FORGET_RECIPIENT: Final = TaskRef("notifications.forget_recipient", UserDeleted)
"""Подписчик UserDeleted: всё о получателе удалённого аккаунта (§7.10)."""
