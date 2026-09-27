"""Пользователи в тестах модулей: вход через Telegram и строка в identity.users.

API-тесты входят так же, как Mini App: подписанный initData → POST /auth/telegram.
Интеграционным тестам модулей выше identity нужен пользователь для FK на identity.users;
код identity им недоступен (import-linter), поэтому строка вставляется SQL-запросом.
"""

import json
from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import UserId, new_id
from app.platform.security.initdata import sign
from app.platform.settings import Settings


def new_telegram_id() -> int:
    """Свой Telegram id на тест: API-тесты коммитят данные."""
    return 500_000_000 + new_id().int % 100_000_000


def signed_init_data(
    settings: Settings,
    telegram_id: int,
    *,
    start_param: str | None = None,
    auth_date: datetime | None = None,
    **user: object,
) -> str:
    """initData Mini App, подписанный токеном бота из настроек теста."""
    profile = {"id": telegram_id, "first_name": "Ana", "language_code": "sr"} | user
    fields = {
        "auth_date": str(int((auth_date or SystemClock().now()).timestamp())),
        "user": json.dumps(profile, separators=(",", ":"), ensure_ascii=False),
    }
    if start_param is not None:
        fields["start_param"] = start_param
    return urlencode(
        fields | {"hash": sign(fields, settings.telegram.bot_token.get_secret_value())}
    )


async def login(api: httpx.AsyncClient, init_data: str) -> dict[str, object]:
    response = await api.post(
        "/api/v1/auth/telegram", headers={"authorization": f"tma {init_data}"}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def bearer(tokens: dict[str, object]) -> dict[str, str]:
    return {"authorization": f"Bearer {tokens['access_token']}"}


def user_id_of(tokens: dict[str, object]) -> UserId:
    user = tokens["user"]
    assert isinstance(user, dict)
    return UserId(UUID(str(user["id"])))


async def insert_user(session: AsyncSession, *, telegram_id: int | None = None) -> UserId:
    """Активный пользователь (и его Telegram, если задан id) в транзакции теста."""
    user_id = UserId(new_id())
    await session.execute(
        text("INSERT INTO identity.users (id, display_name, version) VALUES (:id, 'Ana', 1)"),
        {"id": user_id},
    )
    if telegram_id is not None:
        await session.execute(
            text(
                "INSERT INTO identity.auth_identities (id, user_id, provider, subject)"
                " VALUES (uuidv7(), :user_id, 'telegram', :subject)"
            ),
            {"user_id": user_id, "subject": str(telegram_id)},
        )
    # UoW откатывает транзакцию, в которой «были только чтения»: фиксируем savepoint теста
    await session.commit()
    return user_id
