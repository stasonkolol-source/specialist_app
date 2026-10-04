"""Сборка модуля growth для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.growth.api import GrowthApi
from app.modules.growth.application.facade import GrowthFacade
from app.modules.growth.application.ports import AttributionRepository, ReferralCodes
from app.modules.growth.application.use_cases.create_share import BotLink, CreateShare
from app.modules.growth.application.use_cases.forget_attribution import ForgetAttribution
from app.modules.growth.application.use_cases.record_attribution import RecordAttribution
from app.modules.growth.infrastructure.repositories import (
    SqlAttributionRepository,
    SqlReferralCodes,
)
from app.platform.settings import TelegramSettings


class GrowthProvider(Provider):
    """Провайдер модуля growth: связывает порты с реализациями."""

    scope = Scope.REQUEST

    attributions = provide(SqlAttributionRepository, provides=AttributionRepository)
    referral_codes = provide(SqlReferralCodes, provides=ReferralCodes)
    record_attribution = provide(RecordAttribution)
    forget_attribution = provide(ForgetAttribution)
    create_share = provide(CreateShare)
    facade = provide(GrowthFacade, provides=GrowthApi)

    @provide(scope=Scope.APP)
    def bot_link(self, settings: TelegramSettings) -> BotLink:
        return BotLink(username=settings.bot_username)
