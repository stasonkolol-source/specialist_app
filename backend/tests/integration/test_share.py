"""POST /share (DEVELOPMENT_PLAN 7.4) через API: ссылка на профиль специалиста и заявку — у
вошедшего с его кодом `_r`, у гостя без; карточки в тестах нет (Bot API не зовём — клиент
делится ссылкой). Делиться можно только публичным: неизвестный профиль, прямой запрос и
истёкшая заявка — 404. Данные коммитятся."""

from collections.abc import AsyncIterator

import pytest

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, parse_start_param
from tests.plugins.chat import API, Chat
from tests.plugins.http import http_app
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration


@pytest.fixture
async def chat(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[Chat]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield Chat(app, storage_settings)


async def test_specialist_and_job_links(chat: Chat) -> None:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    sharer = await chat.user(telegram_id=new_id().int % 10**9)
    client = await chat.user()
    job_id = await chat.job(client)

    profile = await chat.post(
        sharer, "/share", {"entity_type": "specialist", "entity_id": str(specialist.profile_id)}
    )
    job = await chat.post(sharer, "/share", {"entity_type": "job", "entity_id": str(job_id)})
    guest = await chat.app.client.post(
        f"{API}/share", json={"entity_type": "job", "entity_id": str(job_id)}
    )

    assert (profile.status_code, job.status_code, guest.status_code) == (200, 200, 200), job.text
    shared, posted, anonymous = profile.json(), job.json(), guest.json()
    link = parse_start_param(shared["start_param"])
    assert link is not None
    assert (link.type, link.id) == (LinkType.SPECIALIST, specialist.profile_id)
    assert shared["url"] == f"https://t.me/sosed_test_bot?startapp={shared['start_param']}"
    assert shared["prepared_message_id"] is None
    assert shared["text"]
    job_link = parse_start_param(posted["start_param"])
    assert job_link is not None
    assert (job_link.type, job_link.id, job_link.ref) == (LinkType.JOB, job_id, link.ref)
    assert link.ref is not None
    assert posted["text"] == "Повесить люстру"
    guest_link = parse_start_param(anonymous["start_param"])
    assert guest_link is not None
    assert (guest_link.type, guest_link.ref) == (LinkType.JOB, None)
    assert profile.headers["cache-control"] == "private, no-store"


async def test_only_public_things_are_shared(chat: Chat) -> None:
    sharer, client = await chat.user(), await chat.user()
    direct = await chat.job(client)
    await chat.execute("UPDATE jobs.jobs SET visibility = 'direct' WHERE id = :id", id=direct)
    expired = await chat.job(client)
    await chat.execute("UPDATE jobs.jobs SET status = 'expired' WHERE id = :id", id=expired)

    replies = [
        await chat.post(sharer, "/share", {"entity_type": kind, "entity_id": str(entity_id)})
        for kind, entity_id in (("specialist", new_id()), ("job", direct), ("job", expired))
    ]
    wrong = await chat.post(sharer, "/share", {"entity_type": "deal", "entity_id": str(new_id())})

    assert [reply.status_code for reply in replies] == [404, 404, 404]
    assert wrong.status_code == 422
