"""Модуль identity собирается из DI-контейнера процесса web (ADR-0020 §7)."""

import pytest

from app.entrypoints._wiring import make_web_container
from app.modules.identity.api import IdentityApi
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.use_cases.authenticate_telegram import AuthenticateTelegram
from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.application.use_cases.refresh_session import RefreshSession
from app.modules.identity.di import bot_id_of
from app.platform.kernel.principal import Platform
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


async def test_use_cases_and_facade_resolve(settings: Settings) -> None:
    container = make_web_container(settings)
    try:
        config = await container.get(IdentityConfig)
        assert config.bot_id == 8123456789
        assert config.refresh_ttl(Platform.TMA).days == settings.jwt.refresh_ttl_days_tma
        assert config.refresh_ttl(Platform.IOS).days == settings.jwt.refresh_ttl_days
        async with container() as request:
            for dependency in (AuthenticateTelegram, RefreshSession, Logout, IdentityApi):
                assert await request.get(dependency) is not None
    finally:
        await container.close()


@pytest.mark.parametrize(
    ("token", "bot_id"), [("123456:ABC", 123456), ("not-a-token", None), (":x", None)]
)
def test_bot_id_is_taken_from_token(token: str, bot_id: int | None) -> None:
    assert bot_id_of(token) == bot_id
