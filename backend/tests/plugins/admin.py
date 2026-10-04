"""Админка в тестах (DEVELOPMENT_PLAN 2.7a–b): приложение с SQLAdmin, сотрудник с ролью и вход.

Данные коммитятся: у каждого теста свои пользователи, логины и адрес клиента (лимиты в Valkey).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pyotp
import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_web_container
from app.interfaces.admin.app import mount_admin
from app.interfaces.http.app import create_app
from app.modules.identity.application.use_cases.create_staff_login import (
    CreateStaffLogin,
    CreateStaffLoginCommand,
)
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.identity import insert_user, new_telegram_id

PASSWORD = "correct horse battery"  # noqa: S105 — пароль тестового сотрудника


@dataclass
class Admin:
    container: AsyncContainer
    settings: Settings

    def client(self, ip: str) -> httpx.AsyncClient:
        app = create_app(self.container, self.settings, [])
        mount_admin(app, self.settings)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True, client=(ip, 50000))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def engine(self) -> AsyncEngine:
        async with self.container() as request:
            engine: AsyncEngine = await request.get(AsyncEngine)
        return engine


@dataclass
class Staff:
    user_id: UserId
    login: str
    secret: str


@pytest.fixture
async def admin(settings: Settings) -> AsyncIterator[Admin]:
    container = make_web_container(settings)
    try:
        yield Admin(container=container, settings=settings)
    finally:
        await container.close()


def client_ip() -> str:
    raw = new_id().int
    return f"10.{raw % 250}.{(raw >> 8) % 250}.{(raw >> 16) % 250 + 1}"


async def staff(admin: Admin, role: str) -> Staff:
    telegram_id = new_telegram_id()
    async with admin.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session, telegram_id=telegram_id)
        await session.execute(
            text("INSERT INTO identity.user_roles (user_id, role) VALUES (:id, :role)"),
            {"id": user_id, "role": role},
        )
        await session.commit()
    # хвост UUIDv7 случайный, а начало — время с шагом 256 мс: два сотрудника одной роли подряд
    # получали один логин (uq_staff_credentials_login)
    login = f"{role}-{new_id().hex[-10:]}"
    async with admin.container() as request:
        created = await (await request.get(CreateStaffLogin))(
            CreateStaffLoginCommand(telegram_id=telegram_id, login=login, password=PASSWORD)
        )
    assert created is not None
    assert created.totp_uri.startswith("otpauth://totp/")
    return Staff(user_id=user_id, login=login, secret=created.totp_secret)


async def login(client: httpx.AsyncClient, who: Staff, *, code: str | None = None) -> int:
    form = {"username": who.login, "password": PASSWORD}
    form["otp"] = pyotp.TOTP(who.secret).now() if code is None else code
    return (await client.post("/admin/login", data=form)).status_code


async def audit_count(admin: Admin, action: str, actor: UserId) -> int:
    async with (await admin.engine()).connect() as conn:
        found = await conn.scalar(
            text(
                "SELECT count(*) FROM platform.audit_log WHERE action = :action"
                " AND actor_id = :actor"
            ),
            {"action": action, "actor": actor},
        )
    return int(found or 0)
