"""Сборка DI-контейнера процесса (ADR-0020 §7).

Один контейнер на процесс: провайдер платформы (появится в шаге 0.11), провайдеры
всех модулей и провайдер интерфейса процесса (web, bot или worker).
"""

from dishka import AsyncContainer, Provider, make_async_container

from app.modules.billing.di import BillingProvider
from app.modules.catalog.di import CatalogProvider
from app.modules.deals.di import DealsProvider
from app.modules.geo.di import GeoProvider
from app.modules.growth.di import GrowthProvider
from app.modules.identity.di import IdentityProvider
from app.modules.jobs.di import JobsProvider
from app.modules.media.di import MediaProvider
from app.modules.messaging.di import MessagingProvider
from app.modules.moderation.di import ModerationProvider
from app.modules.notifications.di import NotificationsProvider
from app.modules.pricing.di import PricingProvider
from app.modules.reviews.di import ReviewsProvider
from app.modules.search.di import SearchProvider
from app.modules.specialists.di import SpecialistsProvider

MODULE_PROVIDERS: tuple[type[Provider], ...] = (
    IdentityProvider,
    GeoProvider,
    CatalogProvider,
    MediaProvider,
    BillingProvider,
    SpecialistsProvider,
    PricingProvider,
    DealsProvider,
    JobsProvider,
    MessagingProvider,
    ReviewsProvider,
    SearchProvider,
    GrowthProvider,
    NotificationsProvider,
    ModerationProvider,
)


def module_providers() -> list[Provider]:
    """Провайдеры всех доменных модулей — одинаковые для web, bot и worker."""
    return [provider() for provider in MODULE_PROVIDERS]


def make_container(*interface_providers: Provider) -> AsyncContainer:
    """Контейнер процесса: модули плюс провайдеры интерфейса конкретного процесса."""
    return make_async_container(*module_providers(), *interface_providers)
