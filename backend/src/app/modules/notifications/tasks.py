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
- `notifications.send` — отправить доставку в бот (очередь `notifications`).
- `notifications.expire_stale` — раз в час: доставки, зависшие в `queued` дольше суток после
  срока, становятся `failed` (`stale`).
"""

from dishka import FromDishka

from app.modules.notifications.application.ports import (
    GRANT_WRITE_ACCESS,
    NOTIFY_ACCOUNT_RESTRICTED,
    NOTIFY_MODERATION_DECISION,
    NOTIFY_PROFILE_PUBLISHED,
    SEND_DELIVERY,
    SendDeliveryPayload,
)
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveries,
    ExpireStaleDeliveriesCommand,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.notify import Notify, NotifyCommand
from app.modules.notifications.application.use_cases.send_delivery import (
    SendDelivery,
    SendDeliveryCommand,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import DeliveryId
from app.platform.contracts.events.identity import BotStarted, RestrictionKind, UserRestricted
from app.platform.contracts.events.moderation import ModerationDecision, ModerationDecisionMade
from app.platform.contracts.events.specialists import ProfilePublished
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task
from app.platform.telegram.deeplinks import LinkDocument, LinkType, StartLink, encode_start_param

RULES_LINK = encode_start_param(StartLink(type=LinkType.LEGAL, document=LinkDocument.TERMS))
HOME_LINK = encode_start_param(StartLink(type=LinkType.HOME))
FIX_LINKS = {"job": LinkType.JOB, "profile": LinkType.SPECIALIST}
"""Куда ведёт «Исправить»: к заявке или профилю; остальное — на Главную (экраны — позже)."""


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
    event: ModerationDecisionMade, notify: FromDishka[Notify]
) -> None:
    if event.decision is not ModerationDecision.REJECTED:
        return
    kind = FIX_LINKS.get(event.entity_type)
    link = encode_start_param(StartLink(type=kind, id=event.entity_id)) if kind else HOME_LINK
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


@periodic("notifications.expire_stale", cron="53 * * * *")
async def expire_stale(run: PeriodicRun) -> None:
    async with run.container() as request:
        expire = await request.get(ExpireStaleDeliveries)
        await expire(ExpireStaleDeliveriesCommand())


@task(SEND_DELIVERY)
async def send(payload: SendDeliveryPayload, deliver: FromDishka[SendDelivery]) -> None:
    await deliver(SendDeliveryCommand(delivery_id=DeliveryId(payload.delivery_id)))
