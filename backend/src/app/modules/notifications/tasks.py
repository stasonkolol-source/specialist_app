"""Задачи notifications (ADR-0020 §3): подписки на события других модулей и отправка.

notifications стоит над контентными модулями (ARCHITECTURE §5.4): они о нём не знают и
публикуют события, а подписчики здесь решают, кому и что написать.

- `notifications.grant_write_access` — BotStarted: /start разрешает боту писать.
- `notifications.notify_account_restricted` — UserRestricted: уведомление о санкции;
  теневой бан человеку не сообщается — на то он и теневой.
- `notifications.notify_profile_published` — ProfilePublished одобренного модерацией профиля:
  «Профиль опубликован» и кнопка к нему (2.8a).
- `notifications.notify_moderation_decision` — ModerationDecisionMade: автору — отказ
  (statement of reasons: причина, предупреждение, автоматически ли) и кнопка «Исправить» к
  его контенту; одобрение без уведомления.
- `notifications.notify_appeal_decided` — AppealDecided: итог апелляции тем же типом
  `moderation.decision` — санкция снята или решение осталось в силе и почему (2.5b).
- `notifications.notify_job_expiring` — JobExpiring: «Заявка закроется через 2 ч» с кнопками
  «Продлить» и «Закрыть: исполнитель найден»; позже срока заявки в бот не уходит.
- `notifications.notify_job_expired` — JobExpired: «Срок заявки вышел», «Продлить» и
  «Закрыть». Оба — только если заявка ещё в том статусе: продлённой и закрытой — ничего.
- `notifications.schedule_responses_notice` — ResponseSubmitted: первый отклик окна ставит
  `notifications.notify_responses` через пять минут, следующие — ничего (дебаунс, 5.4).
- `notifications.notify_responses` — конец окна: клиенту «Новых откликов: 3» и кнопка к
  заявке, если отклики прошли проверку и он их ещё не открыл.
- `notifications.schedule_messages_notice` — MessageSent: первое сообщение окна ставит
  `notifications.notify_messages` получателю через минуту, следующие — ничего (дебаунс, 6.3b).
- `notifications.notify_messages` — конец окна: «Алексей пишет» с началом последнего сообщения и
  кнопкой «Ответить», если получатель ещё не прочитал и не смотрит диалог прямо сейчас.
- `notifications.notify_job_invited` — JobInvited: специалисту «Вас приглашают откликнуться»
  или «Прямой запрос» — кнопка к заявке и «Шаблон «…»» на каждый его шаблон (отклик в один
  тап обрабатывает бот jobs), если заявка ещё открыта (5.6).
- `notifications.notify_response_accepted` — ResponseAccepted: выбранному исполнителю «Клиент
  выбрал вас» и кнопка к сделке (6.1b), если сделка ещё идёт.
- `notifications.notify_passed_over` — ResponseAccepted: остальным откликнувшимся «Клиент выбрал
  другого исполнителя», пока заявка «в работе».
- `notifications.notify_deal_proposed` — DealProposed: второй стороне «Клиент (исполнитель)
  предлагает договориться» и кнопка к условиям, пока предложение ждёт (6.3b).
- `notifications.notify_deal_cancelled` — DealCancelled: второй стороне — кто отменил и почему
  (при отмене системой — обеим, кроме удалённого аккаунта); клиенту из отклика — «заявка снова
  открыта». Отмену модератором по спору объясняет `dispute.resolved`.
- `notifications.notify_dispute_opened` — DealDisputed: второй стороне — «сообщил о проблеме»,
  что случилось, срок ответа (48 ч) и «Ответить» сразу на S52 (`p_`), пока спор ждёт ответа
  (6.1c).
- `notifications.notify_dispute_resolved` — DisputeResolved: обеим сторонам — решение поддержки
  (сделка завершена или отменена) и причина: statement of reasons (6.1c).
- `notifications.notify_deal_reminder` — DealReminderDue: обеим сторонам за 2 ч до времени.
- `notifications.notify_deal_completion` — DealCompletionDue: «Работа выполнена?» с [Да, всё
  хорошо] (кнопку обрабатывает бот deals) и [Есть проблема] тем, кто ещё не отметил.
- `notifications.notify_deal_marked` — DealMarkedDone: то же второй стороне сразу после отметки
  первой: «исполнитель (клиент) отметил работу выполненной. Всё в порядке?» (B2, 7.3).
- `notifications.notify_review_request` — ReviewRequested: клиенту — «Как прошла работа?» и
  «Оставить отзыв» (после завершения, через сутки, за 2 дня до конца окна; 7.2).
- `notifications.notify_review_published` — ReviewPublished: исполнителю — новый отзыв и
  «Ответить на отзыв» (7.2).
- `notifications.forget_recipient` — UserDeleted: лента, каналы и настройки удалённого
  аккаунта удалены (§7.10).
- `notifications.send` — отправить доставку в бот (очередь `notifications`).
- `notifications.expire_stale` — раз в час: доставки, зависшие в `queued` дольше суток после
  срока, становятся `failed` (`stale`).
"""

from typing import Final
from uuid import UUID

from dishka import FromDishka

from app.modules.deals.api import DealNotFoundError, DealsApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import InviteNotice, JobBrief, JobsApi
from app.modules.messaging.api import MessagingApi
from app.modules.notifications.application.ports import (
    FORGET_RECIPIENT,
    GRANT_WRITE_ACCESS,
    NOTIFY_ACCOUNT_RESTRICTED,
    NOTIFY_APPEAL_DECIDED,
    NOTIFY_DEAL_CANCELLED,
    NOTIFY_DEAL_COMPLETION,
    NOTIFY_DEAL_MARKED,
    NOTIFY_DEAL_PROPOSED,
    NOTIFY_DEAL_REMINDER,
    NOTIFY_DISPUTE_OPENED,
    NOTIFY_DISPUTE_RESOLVED,
    NOTIFY_JOB_EXPIRED,
    NOTIFY_JOB_EXPIRING,
    NOTIFY_JOB_INVITED,
    NOTIFY_MESSAGES,
    NOTIFY_MODERATION_DECISION,
    NOTIFY_PASSED_OVER,
    NOTIFY_PROFILE_PUBLISHED,
    NOTIFY_RESPONSE_ACCEPTED,
    NOTIFY_RESPONSES,
    NOTIFY_REVIEW_PUBLISHED,
    NOTIFY_REVIEW_REQUEST,
    SCHEDULE_MESSAGES_NOTICE,
    SCHEDULE_RESPONSES_NOTICE,
    SEND_DELIVERY,
    MessagesWindow,
    ResponsesWindow,
    SendDeliveryPayload,
)
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveries,
    ExpireStaleDeliveriesCommand,
)
from app.modules.notifications.application.use_cases.forget_recipient import (
    ForgetRecipient,
    ForgetRecipientCommand,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.notify import Notify, NotifyCommand
from app.modules.notifications.application.use_cases.schedule_messages_notice import (
    ScheduleMessagesNotice,
    ScheduleMessagesNoticeCommand,
)
from app.modules.notifications.application.use_cases.schedule_responses_notice import (
    ScheduleResponsesNotice,
    ScheduleResponsesNoticeCommand,
)
from app.modules.notifications.application.use_cases.send_delivery import (
    SendDelivery,
    SendDeliveryCommand,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import DeliveryId
from app.modules.reviews.api import ReviewsApi
from app.platform.contracts.events.deals import (
    DealCancelled,
    DealCompletionDue,
    DealDisputed,
    DealMarkedDone,
    DealProposed,
    DealReminderDue,
    DisputeResolved,
)
from app.platform.contracts.events.identity import (
    BotStarted,
    RestrictionKind,
    UserDeleted,
    UserRestricted,
)
from app.platform.contracts.events.jobs import (
    JobExpired,
    JobExpiring,
    JobInvited,
    ResponseAccepted,
    ResponseSubmitted,
)
from app.platform.contracts.events.messaging import MessageSent
from app.platform.contracts.events.moderation import (
    AppealDecided,
    ModerationDecision,
    ModerationDecisionMade,
)
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRequested
from app.platform.contracts.events.specialists import ProfilePublished
from app.platform.kernel.ids import DealId, UserId
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task
from app.platform.telegram.deeplinks import (
    LinkDocument,
    LinkSection,
    LinkType,
    StartLink,
    encode_start_param,
)

TEMPLATE_BUTTONS: Final = 2
"""Кнопок «Откликнуться шаблоном» в уведомлении: шаблонов у исполнителя не больше двух."""

REVIEW_PREVIEW_CHARS: Final = 100
"""Начало отзыва в уведомлении исполнителю — как превью сообщения (6.3b)."""

RULES_LINK = encode_start_param(StartLink(type=LinkType.LEGAL, document=LinkDocument.TERMS))
REVIEWS_LINK = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.REVIEWS))
HOME_LINK = encode_start_param(StartLink(type=LinkType.HOME))
FIX_LINKS = {"job": LinkType.JOB, "profile": LinkType.SPECIALIST}
"""Куда ведёт «Исправить»: к заявке или профилю; отклик — к его заявке; остальное — на
Главную (экраны — позже)."""
RESPONSE = "response"
AGREED, PROPOSED = "agreed", "proposed"
CLIENT, PERFORMER = "client", "performer"
"""Стороны сделки — как `cancelled_by` в DealCancelled."""
BY_DISPUTE = "dispute"
"""Причина отмены модератором по спору: о ней — `dispute.resolved`, а не `deal.cancelled`."""


@subscriber(BotStarted, GRANT_WRITE_ACCESS)
async def grant_write_access(
    event: BotStarted, grant: FromDishka[GrantTelegramWriteAccess]
) -> None:
    """Канал telegram доступен после /start; повтор задачи ничего не меняет."""
    await grant(
        GrantTelegramWriteAccessCommand(
            user_id=event.user_id, via=GrantedVia.BOT_START, at=event.occurred_at
        )
    )


@subscriber(UserRestricted, NOTIFY_ACCOUNT_RESTRICTED)
async def notify_account_restricted(event: UserRestricted, notify: FromDishka[Notify]) -> None:
    if event.kind is RestrictionKind.SHADOW_BANNED:
        return
    params = {"kind": event.kind.value}
    if event.until is not None:
        params["until"] = event.until.isoformat()
    await notify(
        NotifyCommand(
            user_id=event.user_id,
            type=NotificationType.ACCOUNT_RESTRICTED,
            dedupe_key=f"account.restricted:{event.restriction_id}",
            params=params,
            link=RULES_LINK,
        )
    )


@subscriber(ModerationDecisionMade, NOTIFY_MODERATION_DECISION)
async def notify_moderation_decision(
    event: ModerationDecisionMade, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    if event.decision is not ModerationDecision.REJECTED:
        return
    kind = FIX_LINKS.get(event.entity_type)
    link = encode_start_param(StartLink(type=kind, id=event.entity_id)) if kind else HOME_LINK
    if event.entity_type == RESPONSE and (job_id := await jobs.response_job(event.entity_id)):
        link = _job_link(job_id)
    await notify(
        NotifyCommand(
            user_id=event.author_id,
            type=NotificationType.MODERATION_DECISION,
            dedupe_key=f"moderation.decision:{event.case_id}",
            params={
                "entity_type": event.entity_type,
                "decision_code": event.decision_code or "other",
                "automated": "true" if event.automated else "false",
                **({"sanction": event.sanction} if event.sanction else {}),
            },
            link=link,
        )
    )


@subscriber(AppealDecided, NOTIFY_APPEAL_DECIDED)
async def notify_appeal_decided(event: AppealDecided, notify: FromDishka[Notify]) -> None:
    await notify(
        NotifyCommand(
            user_id=event.user_id,
            type=NotificationType.MODERATION_DECISION,
            dedupe_key=f"moderation.decision:{event.case_id}",
            params={
                "entity_type": "appeal",
                "appeal": "granted" if event.granted else "denied",
                "decision_code": event.decision_code or "other",
                "automated": "false",
            },
            link=HOME_LINK,
        )
    )


@subscriber(ProfilePublished, NOTIFY_PROFILE_PUBLISHED)
async def notify_profile_published(event: ProfilePublished, notify: FromDishka[Notify]) -> None:
    if not event.approved:  # владелец вернул скрытый профиль — сообщать нечего
        return
    await notify(
        NotifyCommand(
            user_id=event.user_id,
            type=NotificationType.PROFILE_PUBLISHED,
            dedupe_key=f"profile.published:{event.event_id}",
            params={},
            link=encode_start_param(StartLink(type=LinkType.SPECIALIST, id=event.profile_id)),
        )
    )


@subscriber(JobExpiring, NOTIFY_JOB_EXPIRING)
async def notify_job_expiring(
    event: JobExpiring, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    job = await jobs.job_brief(event.job_id)
    if job is None or job.status != "published" or job.expires_at != event.expires_at:
        return  # пока задача ждала, заявку продлили, закрыли или удалили
    await notify(
        NotifyCommand(
            user_id=event.client_id,
            type=NotificationType.JOB_EXPIRING,
            dedupe_key=f"job.expiring:{event.event_id}",
            params=_job_params(event.job_id, job),
            link=_job_link(event.job_id),
            valid_until=event.expires_at,
        )
    )


@subscriber(JobExpired, NOTIFY_JOB_EXPIRED)
async def notify_job_expired(
    event: JobExpired, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    job = await jobs.job_brief(event.job_id)
    if job is None or job.status != "expired":
        return  # клиент уже продлил или закрыл
    await notify(
        NotifyCommand(
            user_id=event.client_id,
            type=NotificationType.JOB_EXPIRED,
            dedupe_key=f"job.expired:{event.event_id}",
            params=_job_params(event.job_id, job),
            link=_job_link(event.job_id),
        )
    )


@subscriber(ResponseSubmitted, SCHEDULE_RESPONSES_NOTICE)
async def schedule_responses_notice(
    event: ResponseSubmitted, schedule: FromDishka[ScheduleResponsesNotice]
) -> None:
    await schedule(ScheduleResponsesNoticeCommand(job_id=event.job_id, at=event.occurred_at))


@task(NOTIFY_RESPONSES)
async def notify_responses(
    window: ResponsesWindow, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    notice = await jobs.responses_notice(window.job_id)
    if notice is None or notice.status != "published" or notice.unseen == 0:
        return  # заявку закрыли, отклики ещё на проверке или клиент их уже открыл
    await notify(
        NotifyCommand(
            user_id=notice.client_id,
            type=NotificationType.RESPONSE_RECEIVED,
            dedupe_key=f"response.received:{window.job_id}:{window.since.isoformat()}",
            params={
                "job_id": str(window.job_id),
                "title": notice.title,
                "count": str(notice.unseen),
            },
            link=_job_link(window.job_id),
        )
    )


@subscriber(MessageSent, SCHEDULE_MESSAGES_NOTICE)
async def schedule_messages_notice(
    event: MessageSent, schedule: FromDishka[ScheduleMessagesNotice]
) -> None:
    await schedule(
        ScheduleMessagesNoticeCommand(
            conversation_id=event.conversation_id,
            recipient_id=event.recipient_id,
            at=event.occurred_at,
        )
    )


@task(NOTIFY_MESSAGES)
async def notify_messages(
    window: MessagesWindow,
    notify: FromDishka[Notify],
    messaging: FromDishka[MessagingApi],
    identity: FromDishka[IdentityApi],
) -> None:
    notice = await messaging.message_notice(window.conversation_id, window.recipient_id)
    if notice is None:
        return  # всё прочитано или диалог открыт прямо сейчас
    recipient = await identity.get_user(window.recipient_id)
    if recipient is None or recipient.is_deleted:
        return
    sender = await identity.get_user(notice.sender_id)
    params = {
        "name": sender.display_name if sender is not None and not sender.is_deleted else "",
        "count": str(notice.unread),
    }
    if notice.preview is not None:
        params["preview"] = notice.preview
    await notify(
        NotifyCommand(
            user_id=window.recipient_id,
            type=NotificationType.MESSAGE_RECEIVED,
            dedupe_key=(
                f"message.received:{window.conversation_id}:{window.recipient_id}:"
                f"{window.since.isoformat()}"
            ),
            params=params,
            link=_chat_link(window.conversation_id),
        )
    )


@subscriber(JobInvited, NOTIFY_JOB_INVITED)
async def notify_job_invited(
    event: JobInvited, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    notice = await jobs.invite_notice(event.job_id, event.performer_id)
    if notice is None or notice.status != "published":
        return  # пока задача ждала, заявку закрыли или удалили
    await notify(
        NotifyCommand(
            user_id=event.performer_id,
            type=NotificationType.JOB_INVITED,
            dedupe_key=f"job.invited:{event.job_id}:{event.performer_id}",
            params=_invite_params(event, notice),
            link=_job_link(event.job_id),
        )
    )


def _invite_params(event: JobInvited, notice: InviteNotice) -> dict[str, str]:
    """Заявка, клиент и до двух шаблонов приглашённого — кнопки «Шаблон «…»» (MAX_TEMPLATES)."""
    params = {
        "job_id": str(event.job_id),
        "title": notice.title,
        "client": notice.client_name or "",
        "direct": "true" if event.direct else "false",
    }
    for index, template in enumerate(notice.templates[:TEMPLATE_BUTTONS]):
        params[f"template_{index}"] = str(template.id)
        params[f"template_{index}_title"] = template.title
    return params


@subscriber(ResponseAccepted, NOTIFY_RESPONSE_ACCEPTED)
async def notify_response_accepted(
    event: ResponseAccepted, notify: FromDishka[Notify], deals: FromDishka[DealsApi]
) -> None:
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or deal.status != AGREED:
        return  # пока задача ждала, сделку уже отменили
    await notify(
        NotifyCommand(
            user_id=event.performer_id,
            type=NotificationType.RESPONSE_ACCEPTED,
            dedupe_key=f"response.accepted:{event.response_id}",
            params={"title": deal.title},
            link=_deal_link(event.deal_id),
        )
    )


@subscriber(ResponseAccepted, NOTIFY_PASSED_OVER)
async def notify_passed_over(
    event: ResponseAccepted, notify: FromDishka[Notify], jobs: FromDishka[JobsApi]
) -> None:
    job = await jobs.job_brief(event.job_id)
    if job is None or job.status != "assigned":
        return  # сделку отменили — прежние кандидаты снова ждут решения
    for performer_id in await jobs.passed_over(event.job_id):
        await notify(
            NotifyCommand(
                user_id=performer_id,
                type=NotificationType.RESPONSE_NOT_SELECTED,
                dedupe_key=f"response.not_selected:{event.response_id}:{performer_id}",
                params={"title": job.title},
            )
        )


@subscriber(DealProposed, NOTIFY_DEAL_PROPOSED)
async def notify_deal_proposed(
    event: DealProposed,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
) -> None:
    """Второй стороне — «Клиент (исполнитель) предлагает договориться»: условия в тексте, кнопки
    «Подтвердить» и «Отклонить» (бот deals) и ссылка на условия в Mini App (S53)."""
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or deal.status != PROPOSED:
        return  # уже подтвердили, отклонили или истекло
    by_client = event.proposed_by == event.client_id
    other = event.performer_id if by_client else event.client_id
    user = await identity.get_user(other)
    if user is None or user.is_deleted:
        return
    params = {
        "title": deal.title,
        "by": CLIENT if by_client else PERFORMER,
        "deal_id": str(event.deal_id),
    }
    if deal.scheduled_at is not None:
        params["at"] = deal.scheduled_at.isoformat()
    if deal.price_type is not None:
        params["price_type"] = deal.price_type
    if deal.agreed_price is not None:
        params["price"] = str(deal.agreed_price)
    await notify(
        NotifyCommand(
            user_id=other,
            type=NotificationType.DEAL_PROPOSED,
            dedupe_key=f"deal.proposed:{event.deal_id}",
            params=params,
            link=_deal_link(event.deal_id),
        )
    )


@subscriber(DealCancelled, NOTIFY_DEAL_CANCELLED)
async def notify_deal_cancelled(
    event: DealCancelled,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
) -> None:
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or event.reason == BY_DISPUTE:
        return
    sides = ((CLIENT, event.client_id), (PERFORMER, event.performer_id))
    for role, user_id in sides:
        if role == event.cancelled_by:
            continue  # отменивший и так знает
        user = await identity.get_user(user_id)
        if user is None or user.is_deleted:
            continue
        reopened = role == CLIENT and event.job_id is not None
        await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.DEAL_CANCELLED,
                dedupe_key=f"deal.cancelled:{event.deal_id}:{user_id}",
                params={
                    "title": deal.title,
                    "by": event.cancelled_by,
                    "reason": event.reason,
                    "reopened": "true" if reopened else "false",
                },
                link=_deal_link(event.deal_id),
            )
        )


@subscriber(DealReminderDue, NOTIFY_DEAL_REMINDER)
async def notify_deal_reminder(
    event: DealReminderDue, notify: FromDishka[Notify], deals: FromDishka[DealsApi]
) -> None:
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or deal.status != AGREED or deal.scheduled_at != event.scheduled_at:
        return  # сделку отменили или перенесли
    for user_id in (event.client_id, event.performer_id):
        await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.DEAL_REMINDER,
                dedupe_key=f"deal.reminder:{event.deal_id}:{user_id}",
                params={"title": deal.title, "at": event.scheduled_at.isoformat()},
                link=_deal_link(event.deal_id),
                valid_until=event.scheduled_at,
            )
        )


@subscriber(DealCompletionDue, NOTIFY_DEAL_COMPLETION)
async def notify_deal_completion(
    event: DealCompletionDue, notify: FromDishka[Notify], deals: FromDishka[DealsApi]
) -> None:
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or deal.status != AGREED:
        return  # уже завершена или отменена
    asked: list[UserId] = []
    if event.ask_client:
        asked.append(event.client_id)
    if event.ask_performer:
        asked.append(event.performer_id)
    for user_id in asked:
        await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.DEAL_COMPLETION_PROMPT,
                dedupe_key=f"deal.completion_prompt:{event.deal_id}:{user_id}",
                params={"title": deal.title, "deal_id": str(event.deal_id)},
                link=_deal_link(event.deal_id),
            )
        )


@subscriber(ReviewRequested, NOTIFY_REVIEW_REQUEST)
async def notify_review_request(
    event: ReviewRequested,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
    reviews: FromDishka[ReviewsApi],
) -> None:
    """Клиенту — «Как прошла работа?» с кнопкой «Оставить отзыв» (сделка S26). Отзыв уже
    оставлен, окно закрылось или исполнителя нет — не просим."""
    try:
        deal = await deals.deal_for(event.deal_id, event.client_id)
    except DealNotFoundError:
        return
    state = await reviews.review_state(
        deal.id,
        event.client_id,
        client_id=deal.client_id,
        status=deal.status,
        completed_at=deal.completed_at,
    )
    performer = await identity.get_user(event.performer_id)
    if state.open_until is None or performer is None or performer.is_deleted:
        return
    await notify(
        NotifyCommand(
            user_id=event.client_id,
            type=NotificationType.REVIEW_REQUEST,
            dedupe_key=f"review.request:{event.deal_id}:{event.stage}",
            params={
                "title": deal.title,
                "performer": performer.display_name,
                "stage": event.stage,
                "deal_id": str(event.deal_id),
            },
            link=_deal_link(event.deal_id),
            valid_until=state.open_until,
        )
    )


@subscriber(ReviewPublished, NOTIFY_REVIEW_PUBLISHED)
async def notify_review_published(
    event: ReviewPublished,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    reviews: FromDishka[ReviewsApi],
) -> None:
    """Исполнителю — новый отзыв: оценка, начало текста, «Ответить на отзыв» («Мои отзывы»)."""
    review = await reviews.published_review(event.review_id)
    if review is None:
        return  # успели снять
    deal = await deals.deal_brief(event.deal_id) if event.deal_id is not None else None
    params = {"rating": str(review.rating), "title": deal.title if deal is not None else ""}
    if review.body:
        params["preview"] = _preview(review.body)
    await notify(
        NotifyCommand(
            user_id=event.subject_user_id,
            type=NotificationType.REVIEW_PUBLISHED,
            dedupe_key=f"review.published:{event.review_id}",
            params=params,
            link=REVIEWS_LINK,
        )
    )


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= REVIEW_PREVIEW_CHARS:
        return flat
    return flat[: REVIEW_PREVIEW_CHARS - 1].rstrip() + "…"


@subscriber(DealMarkedDone, NOTIFY_DEAL_MARKED)
async def notify_deal_marked(
    event: DealMarkedDone, notify: FromDishka[Notify], deals: FromDishka[DealsApi]
) -> None:
    """Второй стороне — «Работа выполнена?» сразу после отметки первой; тот же ключ, что у
    вопроса по сроку, — второй раз не спросим."""
    deal = await deals.deal_brief(event.deal_id)
    if deal is None or deal.status != AGREED:
        return  # уже завершена или отменена
    other = event.client_id if event.marked_by == PERFORMER else event.performer_id
    await notify(
        NotifyCommand(
            user_id=other,
            type=NotificationType.DEAL_COMPLETION_PROMPT,
            dedupe_key=f"deal.completion_prompt:{event.deal_id}:{other}",
            params={"title": deal.title, "deal_id": str(event.deal_id), "by": event.marked_by},
            link=_deal_link(event.deal_id),
        )
    )


@subscriber(DealDisputed, NOTIFY_DISPUTE_OPENED)
async def notify_dispute_opened(
    event: DealDisputed,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
) -> None:
    """Второй стороне — кто и о чём сообщил, до какого времени ответить; «Ответить» ведёт сразу
    на спор S52. Ответили, отозвали или решили, пока задача ждала, — не пишем."""
    dispute = await deals.dispute(event.dispute_id)
    deal = await deals.deal_brief(event.deal_id)
    if dispute is None or deal is None or dispute.status != "open":
        return
    user = await identity.get_user(event.respondent_id)
    if user is None or user.is_deleted:
        return
    await notify(
        NotifyCommand(
            user_id=event.respondent_id,
            type=NotificationType.DISPUTE_OPENED,
            dedupe_key=f"dispute.opened:{event.dispute_id}",
            params={
                "title": deal.title,
                "by": CLIENT if event.opened_by == event.client_id else PERFORMER,
                "kind": event.kind,
                "until": dispute.respond_by.isoformat(),
            },
            link=_dispute_link(event.deal_id),
        )
    )


@subscriber(DisputeResolved, NOTIFY_DISPUTE_RESOLVED)
async def notify_dispute_resolved(
    event: DisputeResolved,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
) -> None:
    """Обеим сторонам — решение и причина (statement of reasons); удалённому аккаунту — нет."""
    deal = await deals.deal_brief(event.deal_id)
    if deal is None:
        return
    for user_id in (event.client_id, event.performer_id):
        user = await identity.get_user(user_id)
        if user is None or user.is_deleted:
            continue
        await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.DISPUTE_RESOLVED,
                dedupe_key=f"dispute.resolved:{event.dispute_id}:{user_id}",
                params={
                    "title": deal.title,
                    "outcome": event.outcome,
                    "reason": event.reason_code,
                },
                link=_dispute_link(event.deal_id),
            )
        )


def _dispute_link(deal_id: DealId) -> str:
    """Спор S52 сразу, без S26 (`p_`, 6.1c)."""
    return encode_start_param(StartLink(type=LinkType.DISPUTE, id=deal_id))


def _chat_link(conversation_id: UUID) -> str:
    return encode_start_param(StartLink(type=LinkType.CHAT, id=conversation_id))


def _deal_link(deal_id: DealId) -> str:
    return encode_start_param(StartLink(type=LinkType.DEAL, id=deal_id))


def _job_params(job_id: UUID, job: JobBrief) -> dict[str, str]:
    return {
        "job_id": str(job_id),
        "title": job.title,
        "can_extend": "true" if job.can_extend else "false",
    }


def _job_link(job_id: UUID) -> str:
    return encode_start_param(StartLink(type=LinkType.JOB, id=job_id))


@periodic("notifications.expire_stale", cron="53 * * * *")
async def expire_stale(run: PeriodicRun) -> None:
    async with run.container() as request:
        expire = await request.get(ExpireStaleDeliveries)
        await expire(ExpireStaleDeliveriesCommand())


@task(SEND_DELIVERY)
async def send(payload: SendDeliveryPayload, deliver: FromDishka[SendDelivery]) -> None:
    await deliver(SendDeliveryCommand(delivery_id=DeliveryId(payload.delivery_id)))


@subscriber(UserDeleted, FORGET_RECIPIENT)
async def forget_recipient(event: UserDeleted, forget: FromDishka[ForgetRecipient]) -> None:
    await forget(ForgetRecipientCommand(user_id=event.user_id))
