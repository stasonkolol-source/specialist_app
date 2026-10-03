"""«Обычно отвечает за …» (DEVELOPMENT_PLAN 6.3b): медиана от первого сообщения клиента до первого
ответа специалиста в диалогах за 30 дней — в read-model поиска (`search.response_time_stats`) и на
карточке S08. Меньше пяти диалогов с ответом — значения нет; пересборка строки индекса его не
стирает. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.search.application.use_cases.mark_profiles import (
    MarkProfiles,
    MarkProfilesCommand,
)
from app.modules.search.application.use_cases.refresh_response_times import (
    RefreshResponseTimes,
    RefreshResponseTimesCommand,
)
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


@pytest.fixture
async def worker(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def chat(web: HttpApp, storage_settings: Settings) -> AsyncIterator[Chat]:
    created = Chat(web, storage_settings)
    yield created
    engine = await web.container.get(AsyncEngine)
    async with engine.begin() as conn:
        for user_id in created.users:
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id"
                ),
                {"id": f"%{user_id}%"},
            )


async def indexed(chat: Chat) -> Specialist:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    await specialist.handle("search.on_profile_published")
    chat.users.append(specialist.user_id)
    return specialist


async def dialog(
    chat: Chat, specialist: Specialist, *, asked: datetime, reply_after: timedelta | None
) -> None:
    """Клиент пишет специалисту из карточки; специалист отвечает через `reply_after` (или нет).
    Время сообщений — строками: тесту нужны свои часы."""
    client = await chat.user()
    conversation_id = UUID(await chat.start(client, profile_id=str(specialist.profile_id)))
    messages = [(client, asked, "Здравствуйте! Нужна люстра.")]
    if reply_after is not None:
        messages.append((specialist.user_id, asked + reply_after, "Добрый день! Могу завтра."))
    for sender, at, body in messages:
        await chat.execute(
            "INSERT INTO messaging.messages (id, conversation_id, sender_id, kind, body,"
            " created_at) VALUES (uuidv7(), :conversation, :sender, 'text', :body, :at)",
            conversation=conversation_id,
            sender=sender,
            body=body,
            at=at,
        )


async def refresh(worker: AsyncContainer) -> int:
    async with worker() as request:
        return await (await request.get(RefreshResponseTimes))(RefreshResponseTimesCommand())


async def card_minutes(chat: Chat, specialist: Specialist) -> object:
    reply = await chat.app.client.get(f"/api/v1/specialists/{specialist.profile_id}")
    assert reply.status_code == 200, reply.text
    return reply.json()["response_time_minutes"]


async def test_median_first_reply_reaches_the_card(chat: Chat, worker: AsyncContainer) -> None:
    fast, newcomer = await indexed(chat), await indexed(chat)
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    for minutes in (2, 4, 6, 8, 125):  # медиана — 6, а не среднее 29
        await dialog(chat, fast, asked=hour_ago, reply_after=timedelta(minutes=minutes))
    await dialog(chat, fast, asked=hour_ago, reply_after=None)  # без ответа — не в счёт
    await dialog(
        chat, fast, asked=hour_ago - timedelta(days=40), reply_after=timedelta(days=2)
    )  # старше 30 дней
    for minutes in (1, 1, 1, 1):  # четыре диалога — мало
        await dialog(chat, newcomer, asked=hour_ago, reply_after=timedelta(minutes=minutes))

    assert await refresh(worker) >= 1

    assert (await fast.row() or {}).get("response_time_minutes") == 6
    assert (await newcomer.row() or {}).get("response_time_minutes") is None
    assert await card_minutes(chat, fast) == 6
    assert await card_minutes(chat, newcomer) is None

    # пересборка строки индекса время ответа не стирает
    async with chat.app.container() as request:
        await (await request.get(MarkProfiles))(MarkProfilesCommand(profile_ids=[fast.profile_id]))
    await fast.flush()
    assert (await fast.row() or {}).get("response_time_minutes") == 6

    # диалогов с ответом стало меньше пяти — значение снимается
    await chat.execute(
        "DELETE FROM messaging.messages WHERE sender_id = :user AND body = 'Добрый день! Могу"
        " завтра.' AND created_at > now() - interval '2 hours' AND id IN (SELECT id FROM"
        " messaging.messages WHERE sender_id = :user ORDER BY id LIMIT 2)",
        user=UserId(fast.user_id),
    )
    await refresh(worker)
    assert (await fast.row() or {}).get("response_time_minutes") is None
