"""Сроки хранения и выгрузка данных (DEVELOPMENT_PLAN 2.12b, ARCHITECTURE §7.10).

Ночная `platform.retention_sweep` со сдвигом часов: просроченное удаляется — хэши удалённых
аккаунтов, закрытые и отклонённые заявки с откликами, заброшенная переписка, — а сущность под
legal hold (открытый кейс модерации) остаётся. Выгрузка `cli export-user-data` содержит разделы
всех модулей с ПД и пишет audit_log.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_container
from app.platform.kernel.ids import UserId, new_id
from app.platform.privacy.export import EXPORTED, export_user_data
from app.platform.privacy.registry import PRIVACY
from app.platform.privacy.sweep import sweep
from app.platform.settings import Settings
from tests.plugins.identity import insert_user

pytestmark = pytest.mark.integration

MODULES_WITH_PERSONAL_DATA = {
    "deals",
    "growth",
    "identity",
    "jobs",
    "media",
    "messaging",
    "moderation",
    "notifications",
    "pricing",
    "reviews",
    "search",
    "specialists",
}
"""geo и catalog — справочники, billing в MVP пуст (ADR-0018)."""


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    # фото заявок и файлы сообщений правила удаляют через фасад media: ему нужно хранилище
    container = make_container(storage_settings)  # грузит tasks.py и privacy.py модулей
    try:
        yield container
    finally:
        await container.close()


class Db:
    def __init__(self, container: AsyncContainer) -> None:
        self.container = container

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def user(self) -> UserId:
        async with self.container() as request:
            return await insert_user(await request.get(AsyncSession))

    async def job(self, client_id: UUID, *, status: str, ended_at: datetime) -> UUID:
        job_id = new_id()
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND parent_id IS NOT NULL"
        )
        path = await self.scalar("SELECT path FROM catalog.categories WHERE id = :id", id=category)
        closed = status != "rejected"
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, city_id, closed_at, close_reason,"
            " created_at, updated_at, version)"
            " VALUES (:id, :client, :status, 'Повесить люстру', 'Люстра на пять рожков', 'ru',"
            " :category, :path, 'this_week', 'negotiable',"
            " (SELECT id FROM geo.cities WHERE slug = 'novi-sad'), :closed_at, :reason,"
            " :ended, :ended, 1)",
            id=job_id,
            client=client_id,
            status=status,
            category=category,
            path=list(path),
            closed_at=ended_at if closed else None,
            reason="not_needed" if closed else None,
            ended=ended_at,
        )
        return job_id

    async def response(self, job_id: UUID, performer_id: UUID) -> UUID:
        response_id = new_id()
        await self.execute(
            "INSERT INTO jobs.responses (id, job_id, performer_id, status, message, price_type)"
            " VALUES (:id, :job, :performer, 'not_selected', 'Сделаю завтра', 'negotiable')",
            id=response_id,
            job=job_id,
            performer=performer_id,
        )
        return response_id

    async def conversation(self, client_id: UUID, performer_id: UUID, *, at: datetime) -> UUID:
        conversation_id, message_id = new_id(), new_id()
        await self.execute(
            "INSERT INTO messaging.conversations (id, kind, status, client_id, performer_id,"
            " last_message_at, created_at) VALUES (:id, 'direct', 'open', :client, :performer,"
            " :at, :at)",
            id=conversation_id,
            client=client_id,
            performer=performer_id,
            at=at,
        )
        for user_id, role in ((client_id, "client"), (performer_id, "performer")):
            await self.execute(
                "INSERT INTO messaging.participants (conversation_id, user_id, role)"
                " VALUES (:conversation, :user, :role)",
                conversation=conversation_id,
                user=user_id,
                role=role,
            )
        await self.execute(
            "INSERT INTO messaging.messages (id, conversation_id, sender_id, kind, body,"
            " created_at) VALUES (:id, :conversation, :sender, 'text', 'Добрый день', :at)",
            id=message_id,
            conversation=conversation_id,
            sender=client_id,
            at=at,
        )
        return conversation_id

    async def open_case(self, entity_type: str, entity_id: UUID, subject_id: UUID) -> None:
        await self.execute(
            "INSERT INTO moderation.cases (id, queue, entity_type, entity_id, subject_id,"
            " trigger, status, due_at) VALUES (:id, 'safety', :type, :entity, :subject,"
            " 'report', 'pending', now() + interval '1 day')",
            id=new_id(),
            type=entity_type,
            entity=entity_id,
            subject=subject_id,
        )

    async def exists(self, table: str, row_id: UUID) -> bool:
        return bool(await self.scalar(f"SELECT count(*) FROM {table} WHERE id = :id", id=row_id))


@pytest.fixture
def db(container: AsyncContainer) -> Db:
    return Db(container)


async def test_sweep_deletes_expired_and_keeps_legal_hold(
    container: AsyncContainer, db: Db
) -> None:
    now = datetime.now(UTC)
    client, performer = await db.user(), await db.user()
    closed = await db.job(client, status="closed", ended_at=now)
    response = await db.response(closed, performer)
    rejected = await db.job(client, status="rejected", ended_at=now)
    held_job = await db.job(client, status="completed", ended_at=now)
    await db.open_case("job", held_job, client)
    recent = await db.job(client, status="closed", ended_at=now + timedelta(days=400))
    chat = await db.conversation(client, performer, at=now)
    held_chat = await db.conversation(client, await db.user(), at=now)  # пара direct — одна
    reported = await db.scalar(
        "SELECT id FROM messaging.messages WHERE conversation_id = :id", id=held_chat
    )
    await db.open_case("message", reported, client)
    digest = new_id().bytes + new_id().bytes
    await db.execute(
        "INSERT INTO identity.deleted_identity_hashes (hash, kind, had_sanctions, deleted_at,"
        " purge_after) VALUES (:hash, 'telegram', false, :now, :purge)",
        hash=digest,
        now=now,
        purge=now + timedelta(days=365),
    )

    # через полгода с небольшим: отклонённая заявка ушла, остальное ещё в сроке
    report = await sweep(container, now=now + timedelta(days=190))

    assert set(report) >= {
        "identity.deleted_identity_hashes",
        "jobs.jobs_and_responses",
        "messaging.conversations",
    }
    assert -1 not in report.values()
    assert not await db.exists("jobs.jobs", rejected)
    assert await db.exists("jobs.jobs", closed)
    assert await db.exists("messaging.conversations", chat)

    # через 25 месяцев: просроченное удалено, под legal hold — осталось
    await sweep(container, now=now + timedelta(days=760))

    assert not await db.exists("jobs.jobs", closed)
    assert not await db.exists("jobs.responses", response)
    assert await db.exists("jobs.jobs", held_job)
    assert await db.exists("jobs.jobs", recent)  # закрыта позже: 24 месяца ещё не прошли
    assert not await db.exists("messaging.conversations", chat)
    assert (
        await db.scalar(
            "SELECT count(*) FROM messaging.messages WHERE conversation_id = :id", id=chat
        )
        == 0
    )
    assert await db.exists("messaging.conversations", held_chat)
    assert not await db.scalar(
        "SELECT count(*) FROM identity.deleted_identity_hashes WHERE hash = :hash", hash=digest
    )


async def test_job_with_live_conversation_waits_for_it(container: AsyncContainer, db: Db) -> None:
    """Переписка держит FK на заявку: заявку удаляют только после диалога."""
    now = datetime.now(UTC)
    client, performer = await db.user(), await db.user()
    job_id = await db.job(client, status="closed", ended_at=now)
    response_id = await db.response(job_id, performer)
    chat = new_id()
    await db.execute(
        "INSERT INTO messaging.conversations (id, kind, status, client_id, performer_id, job_id,"
        " response_id, last_message_at) VALUES (:id, 'job_response', 'open', :client,"
        " :performer, :job, :response, :at)",
        id=chat,
        client=client,
        performer=performer,
        job=job_id,
        response=response_id,
        at=now + timedelta(days=500),  # разговор продолжился после закрытия заявки
    )

    report = await sweep(container, now=now + timedelta(days=760))

    assert -1 not in report.values()
    assert await db.exists("jobs.jobs", job_id)
    assert await db.exists("messaging.conversations", chat)

    await sweep(container, now=now + timedelta(days=900))

    assert not await db.exists("messaging.conversations", chat)
    assert not await db.exists("jobs.jobs", job_id)


async def test_export_has_every_module_section_and_writes_audit(
    container: AsyncContainer, db: Db
) -> None:
    now = datetime.now(UTC)
    client, performer = await db.user(), await db.user()
    job_id = await db.job(client, status="closed", ended_at=now)
    await db.response(job_id, performer)
    await db.conversation(client, performer, at=now)

    exported = await export_user_data(container, client, now=now, note="ticket-42")

    assert set(PRIVACY.sections) == MODULES_WITH_PERSONAL_DATA
    assert set(exported["sections"]) == MODULES_WITH_PERSONAL_DATA
    sections = exported["sections"]
    assert [row["id"] for row in sections["identity"]["users"]] == [str(client)]
    assert [row["id"] for row in sections["jobs"]["jobs"]] == [str(job_id)]
    assert sections["jobs"]["responses"] == []  # отклик — данные исполнителя
    assert len(sections["messaging"]["messages"]) == 1
    assert sections["media"]["links"] == []
    assert sections["pricing"] == {"services": []}
    json.dumps(exported)  # файл для пользователя — валидный JSON
    audit = await db.scalar(
        "SELECT changes FROM platform.audit_log WHERE action = :action AND entity_id = :user",
        action=EXPORTED,
        user=client,
    )
    assert audit == {"sections": sorted(MODULES_WITH_PERSONAL_DATA), "note": "ticket-42"}
