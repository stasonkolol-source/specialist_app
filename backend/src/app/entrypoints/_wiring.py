"""Сборка DI-контейнера процесса (ADR-0020 §7).

Один контейнер на процесс: PlatformProvider, провайдеры всех модулей и провайдер
интерфейса процесса. У worker провайдера интерфейса нет: use case получает actor_id в
команде, и зависимость от Principal упадёт при сборке контейнера, а не в рантайме.
"""

import importlib
import importlib.util

from dishka import AsyncContainer, Provider, make_async_container
from dishka.integrations.aiogram import AiogramProvider
from dishka.integrations.fastapi import FastapiProvider
from fastapi import APIRouter

from app.interfaces.bot.di import BotProvider
from app.interfaces.http.di import HttpProvider
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
from app.platform.di import PlatformProvider
from app.platform.i18n.translator import Translator
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.tasks import TASKS
from app.platform.settings import Settings

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


def _module_packages() -> list[str]:
    return [provider.__module__.rsplit(".", 1)[0] for provider in MODULE_PROVIDERS]


def load_module_tasks() -> None:
    """Импортировать tasks.py модулей: декораторы @task и @subscriber заполняют TASKS."""
    for package in _module_packages():
        if importlib.util.find_spec(f"{package}.tasks") is not None:
            importlib.import_module(f"{package}.tasks")


def module_routers() -> list[APIRouter]:
    """Роутеры модулей: `router` из modules/<m>/http/router.py, у кого он есть."""
    routers: list[APIRouter] = []
    for package in _module_packages():
        if importlib.util.find_spec(f"{package}.http") is None:
            continue
        module = importlib.import_module(f"{package}.http.router")
        routers.append(module.router)
    return routers


def build_event_registry() -> EventRegistry:
    """Подписки модулей на события — одна функция для web, bot и worker."""
    load_module_tasks()
    return TASKS.event_registry()


def make_container(
    settings: Settings,
    *interface_providers: Provider,
    registry: EventRegistry | None = None,
    translator: Translator | None = None,
) -> AsyncContainer:
    """Контейнер процесса: платформа, модули и провайдеры интерфейса процесса."""
    return make_async_container(
        PlatformProvider(),
        *module_providers(),
        *interface_providers,
        context={
            Settings: settings,
            EventRegistry: registry or build_event_registry(),
            Translator: translator or Translator.load(),
        },
    )


def make_web_container(settings: Settings, translator: Translator | None = None) -> AsyncContainer:
    return make_container(settings, FastapiProvider(), HttpProvider(), translator=translator)


def make_bot_container(settings: Settings) -> AsyncContainer:
    return make_container(settings, AiogramProvider(), BotProvider())


def make_worker_container(settings: Settings) -> AsyncContainer:
    return make_container(settings)
