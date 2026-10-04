"""Диалог глазами участника для экранов (S29 список, шапка S30; DEVELOPMENT_PLAN 6.4): кто вторая
сторона (имя, ссылка на карточку специалиста), о какой заявке речь и что со сделкой. Данные
других модулей — из их фасадов, пачкой на страницу: запросов столько же, сколько модулей, а не
диалогов. Блокировка со второй стороной (4.7) — в карточке: писать нельзя, а «Разблокировать» —
тому, кто заблокировал. Открыты ли контакты — по тому же правилу, что маскирует сообщения и
пускает «Поделиться контактом» (contacts.py): клиент не вычисляет его по статусу сделки сам.
"""

from collections.abc import Mapping, Sequence
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
    """«@username» второй стороны — когда контакты открыты и она показывает Telegram (S43, 6.5)."""
    contacts_open: bool = False
    """Стороны договорились в этом диалоге — сейчас или раньше (ADR-0010, решение 2026-10-04)."""
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
        opened = await self._contacts_open(views, deals)
        telegram = (
            await self._identity.telegram_contacts(
                {v.counterpart_id for v in views if v.id in opened}
            )
            if opened
            else {}
        )
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
                    # по этому диалогу: с той же стороной может быть и другой, где не договорились
                    counterpart_telegram=(
                        telegram.get(view.counterpart_id) if view.id in opened else None
                    ),
                    contacts_open=view.id in opened,
                    block=blocks.get(view.counterpart_id),
                )
            )
        return cards

    async def _contacts_open(
        self, views: Sequence[ConversationView], deals: Mapping[DealId, DealBrief]
    ) -> frozenset[UUID]:
        """Диалоги страницы с открытыми контактами — правило contacts.py пачкой: сделка диалога
        договорена, под спором или завершена, а у остальных со сделкой — договаривались ли раньше
        (одним запросом на страницу). Диалог по отклику, где сделку ещё не связали с диалогом
        (подписчик DealAgreed в очереди), спрашиваем по отклику — как маскирует отправка."""
        settled: set[UUID] = set()
        earlier: dict[UUID, UUID | None] = {}
        for view in views:
            deal = deals.get(DealId(view.deal_id)) if view.deal_id is not None else None
            if deal is not None and deal.status in OPEN_DEALS:
                settled.add(view.id)
            elif view.deal_id is not None or view.response_id is not None:
                earlier[view.id] = view.response_id
        if earlier:
            settled |= await self._deals.agreed_conversations(earlier)
        return frozenset(settled)
