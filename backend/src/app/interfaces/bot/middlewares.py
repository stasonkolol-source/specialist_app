"""Прослойки бота (DEVELOPMENT_PLAN 0.22, ADR-0020 §9): пользователь, локаль, логи, ошибки.

- Пользователь по `from.id` находится чтением через identity (до use case бот в БД не
  пишет); найден — в данных хендлера `principal` и `locale` из его ui_locale, нет — локаль
  из language_code клиента. Telegram id в логи не пишем: только внутренний user_id.
- Доменная ошибка → сообщение на языке пользователя (`errors.<code>`), прочие — общий
  текст, Sentry и лог. Тексты сообщений пользователей не логируются.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import sentry_sdk
import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User

from app.modules.identity.api import IdentityApi
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import DomainError
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Platform, Principal
from app.platform.observability.logging import bind_context, clear_context

log = structlog.get_logger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

_LANGUAGE_LOCALES = {
    "ru": Locale.RU,
    "uk": Locale.RU,
    "be": Locale.RU,
    "kk": Locale.RU,
    "en": Locale.EN,
}


def locale_from_telegram(language_code: str | None) -> Locale:
    if not language_code:
        return Locale.RU
    base = language_code.lower().split("-")[0]
    if base in {"sr", "hr", "bs", "me"}:
        return Locale.SR_LATN
    return _LANGUAGE_LOCALES.get(base, Locale.RU)


def author_of(event: TelegramObject) -> User | None:
    inner: TelegramObject | None = event
    if isinstance(event, Update):
        inner = event.event
    if isinstance(inner, Message | CallbackQuery):
        return inner.from_user
    return None


class UserMiddleware(BaseMiddleware):
    """Кладёт в данные `principal` (если пользователь есть) и `locale`."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        author = author_of(event)
        data["locale"] = locale_from_telegram(author.language_code if author else None)
        if author is not None and not author.is_bot:
            identity: IdentityApi = await data["dishka_container"].get(IdentityApi)
            user = await identity.by_telegram(author.id)
            if user is not None:
                data["locale"] = user.ui_locale
                data["principal"] = Principal(
                    user_id=user.id, trust_level=user.trust_level, platform=Platform.TMA
                )
                bind_context(user_id=str(user.id))
        return await handler(event, data)


class ErrorMiddleware(BaseMiddleware):
    """Ошибки хендлеров → сообщение пользователю на его языке (ADR-0020 §9, колонка «Бот»)."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        try:
            return await handler(event, data)
        except DomainError as exc:
            log.info("bot_domain_error", code=exc.code)
            await self._reply(event, data, f"errors.{exc.code}")
        except Exception:
            sentry_sdk.capture_exception()
            log.exception("bot_handler_failed")
            await self._reply(event, data, "errors.internal_error")
        finally:
            clear_context()
        return None

    async def _reply(self, event: TelegramObject, data: dict[str, Any], key: str) -> None:
        inner = event.event if isinstance(event, Update) else event
        if not isinstance(inner, Message | CallbackQuery):
            return
        translator: Translator = await data["dishka_container"].get(Translator)
        text = translator.text(key, data.get("locale", Locale.RU)) or key
        if isinstance(inner, CallbackQuery):
            # нажатие кнопки ждёт ответа: без него у человека крутится индикатор
            await inner.answer(text, show_alert=True)
            return
        # тексты ошибок с параметрами из данных — простым текстом, а не HTML бота
        await inner.answer(text, parse_mode=None)
