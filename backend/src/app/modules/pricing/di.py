"""Сборка модуля pricing для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.price_list import ServicesPriceList
from app.modules.pricing.application.queries import PriceListQueries
from app.modules.pricing.application.use_cases.add_service import AddService
from app.modules.pricing.application.use_cases.change_service import ChangeService
from app.modules.pricing.application.use_cases.remove_service import RemoveService
from app.modules.pricing.application.use_cases.reorder_services import ReorderServices
from app.modules.pricing.infrastructure.repositories import SqlServiceRepository
from app.modules.specialists.api import PriceList


class PricingProvider(Provider):
    """Провайдер модуля pricing: связывает порты с реализациями."""

    scope = Scope.REQUEST

    services = provide(SqlServiceRepository, provides=ServiceRepository)
    price_list = provide(ServicesPriceList, provides=PriceList)
    """Порт specialists: «Специалиста» без прайса на проверку не отправить (2.8b)."""
    queries = provide(PriceListQueries)
    add_service = provide(AddService)
    change_service = provide(ChangeService)
    remove_service = provide(RemoveService)
    reorder_services = provide(ReorderServices)
