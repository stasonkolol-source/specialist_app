"""Диалог глазами участника для экранов (S29 список, шапка S30; DEVELOPMENT_PLAN 6.4): кто вторая
сторона (имя, ссылка на карточку специалиста), о какой заявке речь и что со сделкой. Данные
других модулей — из их фасадов, пачкой на страницу: запросов столько же, сколько модулей, а не
диалогов. Блокировка со второй стороной (4.7) — в карточке: писать нельзя, а «Разблокировать» —
тому, кто заблокировал.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.deals.api import DealBrief, DealsApi
from app.modules.identity.api import BlockSide, IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.messaging.application.contacts import OPEN_DEALS
from app.modules.messaging.application.dto import ConversationView
from app.modules.messaging.domain.conversation import ParticipantRole
from app.modules.specialists.api import SpecialistsApi
from app.platform.kernel.ids import DealId, UserId

PUBLISHED: Final = "published"
"""Карточка специалиста открыта только у опубликованного профиля."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationCard:
    view: ConversationView
    counterpart_name: str | None
    """Имя на карточке специалиста или имя аккаунта; None — аккаунт второй стороны удалён."""
    counterpart_profile_id: UUID | None
    """Опубликованный профиль второй стороны-исполнителя: шапка S30 ведёт на S08."""
    job_title: str | None
    """Заявка диалога по отклику («Заявка: …» на S29)."""
    deal: DealBrief | None
    """Сделка диалога: «Ещё не договорились», «Предложено», «Договорились»."""
    counterpart_telegram: str | None = None
    """«@username» второй стороны — когда договорились и она показывает Telegram (S43, 6.5)."""
    block: BlockSide | None = None
    """Блокировка со второй стороной (4.7): переписка закрыта, пока она есть."""


class ConversationCards:
    def __init__(
        self,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        jobs: JobsApi,
        deals: DealsApi,
    ) -> None:
        self._identity, self._specialists = identity, specialists
        self._jobs, self._deals = jobs, deals

    async def of(
        self, views: Sequence[ConversationView], viewer_id: UserId
    ) -> list[ConversationCard]:
        if not views:
            return []
        counterparts = {view.counterpart_id for view in views}
        users = await self._identity.users(counterparts)
        blocks = await self._identity.blocks_with(viewer_id, counterparts)
        performers = {v.counterpart_id for v in views if v.my_role is ParticipantRole.CLIENT}
        profiles = await self._specialists.profiles_of(performers)
        titles = await self._jobs.job_titles({v.job_id for v in views if v.job_id is not None})
        deals = await self._deals.deal_briefs(
            {DealId(v.deal_id) for v in views if v.deal_id is not None}
        )
        agreed = {
            v.counterpart_id
            for v in views
            if v.deal_id is not None
            and (deal := deals.get(DealId(v.deal_id))) is not None
            and deal.status in OPEN_DEALS
        }
        telegram = await self._identity.telegram_contacts(agreed) if agreed else {}
        cards = []
        for view in views:
            user = users.get(view.counterpart_id)
            profile = profiles.get(view.counterpart_id)
            public = profile if profile is not None and profile.status == PUBLISHED else None
            name = None
            if user is not None and not user.is_deleted:
                name = (public.display_name if public else None) or user.display_name
            cards.append(
                ConversationCard(
                    view=view,
                    counterpart_name=name,
                    counterpart_profile_id=public.id if public is not None else None,
                    job_title=titles.get(view.job_id) if view.job_id is not None else None,
                    deal=deals.get(DealId(view.deal_id)) if view.deal_id is not None else None,
                    counterpart_telegram=telegram.get(view.counterpart_id),
                    block=blocks.get(view.counterpart_id),
                )
            )
        return cards
