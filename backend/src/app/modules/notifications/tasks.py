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
- `notifications.notify_job_expiring` — JobExpiring: «Заявка закроется через 2 ч» с кнопками
  «Продлить» и «Закрыть: исполнитель найден»; позже срока заявки в бот не уходит.
- `notifications.notify_job_expired` — JobExpired: «Срок заявки вышел», «Продлить» и
  «Закрыть». Оба — только если заявка ещё в том статусе: продлённой и закрытой — ничего.
- `notifications.schedule_responses_notice` — ResponseSubmitted: первый отклик окна ставит
  `notifications.notify_responses` через пять минут, следующие — ничего (дебаунс, 5.4).
- `notifications.notify_responses` — конец окна: клиенту «Новых откликов: 3» и кнопка к
  заявке, если отклики прошли проверку и он их ещё не открыл.
- `notifications.notify_job_invited` — JobInvited: специалисту «Вас приглашают откликнуться»
  или «Прямой запрос» — кнопка к заявке и «Шаблон «…»» на каждый его шаблон (отклик в один
  тап обрабатывает бот jobs), если заявка ещё открыта (5.6).
- `notifications.notify_response_accepted` — ResponseAccepted: выбранному исполнителю «Клиент
  выбрал вас» и кнопка к сделке (6.1b), если сделка ещё идёт.
- `notifications.notify_passed_over` — ResponseAccepted: остальным откликнувшимся «Клиент выбрал
  другого исполнителя», пока заявка «в работе».
- `notifications.notify_deal_cancelled` — DealCancelled: второй стороне — кто отменил и почему
  (при отмене системой — обеим, кроме удалённого аккаунта); клиенту из отклика — «заявка снова
  открыта».
- `notifications.notify_deal_reminder` — DealReminderDue: обеим сторонам за 2 ч до времени.
- `notifications.notify_deal_completion` — DealCompletionDue: «Работа выполнена?» с [Да,
  выполнено] (кнопку обрабатывает бот deals) и [Нет, проблема] тем, кто ещё не отметил.
- `notifications.forget_recipient` — UserDeleted: лента, каналы и настройки удалённого
  аккаунта удалены (§7.10).
- `notifications.send` — отправить доставку в бот (очередь `notifications`).
- `notifications.expire_stale` — раз в час: доставки, зависшие в `queued` дольше суток после
  срока, становятся `failed` (`stale`).
"""

from typing import Final
from uuid import UUID

from dishka import FromDishka

from app.modules.deals.api import DealsApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import InviteNotice, JobBrief, JobsApi
from app.modules.notifications.application.ports import (
    FORGET_RECIPIENT,
    GRANT_WRITE_ACCESS,
    NOTIFY_ACCOUNT_RESTRICTED,
    NOTIFY_DEAL_CANCELLED,
    NOTIFY_DEAL_COMPLETION,
    NOTIFY_DEAL_REMINDER,
    NOTIFY_JOB_EXPIRED,
    NOTIFY_JOB_EXPIRING,
    NOTIFY_JOB_INVITED,
    NOTIFY_MODERATION_DECISION,
    NOTIFY_PASSED_OVER,
    NOTIFY_PROFILE_PUBLISHED,
    NOTIFY_RESPONSE_ACCEPTED,
    NOTIFY_RESPONSES,
    SCHEDULE_RESPONSES_NOTICE,
    SEND_DELIVERY,
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
from app.platform.contracts.events.deals import DealCancelled, DealCompletionDue, DealReminderDue
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
from app.platform.contracts.events.moderation import ModerationDecision, ModerationDecisionMade
from app.platform.contracts.events.specialists import ProfilePublished
from app.platform.kernel.ids import DealId, UserId
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task
from app.platform.telegram.deeplinks import LinkDocument, LinkType, StartLink, encode_start_param

TEMPLATE_BUTTONS: Final = 2
"""Кнопок «Откликнуться шаблоном» в уведомлении: шаблонов у исполнителя не больше двух."""

RULES_LINK = encode_start_param(StartLink(type=LinkType.LEGAL, document=LinkDocument.TERMS))
HOME_LINK = encode_start_param(StartLink(type=LinkType.HOME))
FIX_LINKS = {"job": LinkType.JOB, "profile": LinkType.SPECIALIST}
"""Куда ведёт «Исправить»: к заявке или профилю; отклик — к его заявке; остальное — на
Главную (экраны — позже)."""
RESPONSE = "response"
AGREED = "agreed"
CLIENT, PERFORMER = "client", "performer"
"""Стороны сделки — как `cancelled_by` в DealCancelled."""


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


@subscriber(DealCancelled, NOTIFY_DEAL_CANCELLED)
async def notify_deal_cancelled(
    event: DealCancelled,
    notify: FromDishka[Notify],
    deals: FromDishka[DealsApi],
    identity: FromDishka[IdentityApi],
) -> None:
    deal = await deals.deal_brief(event.deal_id)
    if deal is None:
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
