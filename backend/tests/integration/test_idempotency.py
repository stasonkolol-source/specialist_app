"""Idempotency-Key у создающих POST (DEVELOPMENT_PLAN 1.1, ADR-0020 §4)."""

import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import procrastinate
import procrastinate.testing
import pytest
from dishka.integrations.fastapi import FromDishka, inject
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.platform_tables import audit_log, idempotency_keys
from app.platform.db.port import UnitOfWork
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.errors import ConflictError
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Principal
from app.platform.queue.periodic import idempotency_cleanup
from app.platform.queue.tasks import PeriodicRun
from app.platform.security.jwt import AccessTokens, JwtKeys
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, http_app, sample_router

pytestmark = pytest.mark.integration


class NoteIn(BaseModel):
    text: str


class FlakyError(ConflictError):
    code = "conflict"


failures: dict[str, int] = {}

router = sample_router()
creating = idempotent_router(dependencies=AUTHENTICATED)


@creating.post("/notes", status_code=201)
@inject
async def create_note(
    body: NoteIn,
    principal: FromDishka[Principal],
    uow: FromDishka[UnitOfWork],
    audit: FromDishka[AuditLog],
) -> dict[str, str]:
    """Создаёт запись аудита — побочный эффект, который нельзя повторить дважды."""
    if failures.get(body.text, 0) > 0:
        failures[body.text] -= 1
        raise FlakyError
    note_id = new_id()
    async with uow:
        await audit.record(
            AuditEntry(
                action="test.note.created",
                actor_kind=ActorKind.USER,
                actor_id=principal.user_id,
                entity_type="test.note",
                entity_id=note_id,
                changes={"text": body.text},
            )
        )
    return {"id": str(note_id), "text": body.text}


router.include_router(creating)


def bearer(settings: Settings, user_id: UUID | None = None) -> dict[str, str]:
    assert settings.jwt.keys is not None
    tokens = AccessTokens(
        JwtKeys.parse(settings.jwt.keys.get_secret_value()),
        SystemClock(),
        issuer=settings.jwt.issuer,
        ttl=timedelta(minutes=15),
    )
    principal = Principal(user_id=UserId(user_id or new_id()), session_id=new_id().hex)
    token, _ = tokens.issue(principal, amr=("test",))
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[HttpApp]:
    failures.clear()
    async with http_app(settings, router) as app:
        yield app


async def notes(app: HttpApp, text_value: str) -> int:
    engine = await app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        query = select(func.count()).where(
            audit_log.c.action == "test.note.created",
            audit_log.c.changes["text"].astext == text_value,
        )
        return int((await conn.execute(query)).scalar_one())


async def test_repeat_with_same_key_returns_same_response_once(
    app: HttpApp, settings: Settings
) -> None:
    headers = bearer(settings) | {"idempotency-key": f"key-{new_id().hex}"}
    text_value = f"note-{new_id().hex}"
    first = await app.client.post("/api/v1/test/notes", json={"text": text_value}, headers=headers)
    second = await app.client.post("/api/v1/test/notes", json={"text": text_value}, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "idempotency-replayed" not in first.headers
    assert second.headers["idempotency-replayed"] == "true"
    assert await notes(app, text_value) == 1


async def test_same_key_with_other_body_is_rejected(app: HttpApp, settings: Settings) -> None:
    headers = bearer(settings) | {"idempotency-key": f"key-{new_id().hex}"}
    await app.client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers)
    other = await app.client.post("/api/v1/test/notes", json={"text": "b"}, headers=headers)
    assert other.status_code == 422
    assert other.json()["code"] == "idempotency_key_reused"


@pytest.mark.parametrize(
    ("key", "code"),
    [
        (None, "idempotency_key_required"),
        ("short", "invalid_idempotency_key"),
        ("bad key!!", "invalid_idempotency_key"),
    ],
)
async def test_key_is_required_and_validated(
    app: HttpApp, settings: Settings, key: str | None, code: str
) -> None:
    headers = bearer(settings) | ({"idempotency-key": key} if key else {})
    response = await app.client.post("/api/v1/test/notes", json={"text": "x"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == code


async def test_authentication_comes_first(app: HttpApp) -> None:
    response = await app.client.post("/api/v1/test/notes", json={"text": "x"})
    assert response.status_code == 401


async def test_failed_request_releases_key(app: HttpApp, settings: Settings) -> None:
    text_value = f"flaky-{new_id().hex}"
    failures[text_value] = 1
    headers = bearer(settings) | {"idempotency-key": f"key-{new_id().hex}"}
    failed = await app.client.post("/api/v1/test/notes", json={"text": text_value}, headers=headers)
    retried = await app.client.post(
        "/api/v1/test/notes", json={"text": text_value}, headers=headers
    )
    assert failed.status_code == 409
    assert retried.status_code == 201
    assert "idempotency-replayed" not in retried.headers
    assert await notes(app, text_value) == 1


async def test_request_in_progress_is_conflict(app: HttpApp, settings: Settings) -> None:
    user_id, key, body = new_id(), f"key-{new_id().hex}", b'{"text":"x"}'
    engine = await app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        digest = hashlib.sha256(b"POST /api/v1/test/notes?\n" + body).digest()
        await conn.execute(
            idempotency_keys.insert().values(user_id=user_id, key=key, request_hash=digest)
        )
    headers = bearer(settings, user_id) | {
        "idempotency-key": key,
        "content-type": "application/json",
    }
    response = await app.client.post("/api/v1/test/notes", content=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_in_progress"


async def test_cleanup_removes_expired_keys(app: HttpApp) -> None:
    old, fresh = f"key-{new_id().hex}", f"key-{new_id().hex}"
    user_id = new_id()
    engine = await app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            idempotency_keys.insert(),
            [
                {"user_id": user_id, "key": old, "request_hash": b"\0" * 32},
                {"user_id": user_id, "key": fresh, "request_hash": b"\0" * 32},
            ],
        )
        await conn.execute(
            update(idempotency_keys)
            .where(idempotency_keys.c.key == old)
            .values(created_at=text("now() - interval '25 hours'"))
        )
    await idempotency_cleanup(
        PeriodicRun(
            app=procrastinate.App(connector=procrastinate.testing.InMemoryConnector()),
            container=app.container,
            timestamp=0,
        )
    )
    async with engine.connect() as conn:
        left = (
            (
                await conn.execute(
                    select(idempotency_keys.c.key).where(idempotency_keys.c.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
    assert left == [fresh]


async def test_keys_are_per_user_and_expire(app: HttpApp, settings: Settings) -> None:
    key, text_value = f"key-{new_id().hex}", f"note-{new_id().hex}"
    alice, bob = new_id(), new_id()
    body = {"text": text_value}
    await app.client.post(
        "/api/v1/test/notes", json=body, headers=bearer(settings, alice) | {"idempotency-key": key}
    )
    await app.client.post(
        "/api/v1/test/notes", json=body, headers=bearer(settings, bob) | {"idempotency-key": key}
    )
    assert await notes(app, text_value) == 2

    engine = await app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            update(idempotency_keys)
            .where(idempotency_keys.c.user_id == alice, idempotency_keys.c.key == key)
            .values(created_at=text("now() - interval '25 hours'"))
        )
    again = await app.client.post(
        "/api/v1/test/notes", json=body, headers=bearer(settings, alice) | {"idempotency-key": key}
    )
    assert "idempotency-replayed" not in again.headers
    assert await notes(app, text_value) == 3


async def test_key_header_is_documented(app: HttpApp) -> None:
    spec = (await app.client.get("/api/v1/openapi.json")).json()
    params = spec["paths"]["/api/v1/test/notes"]["post"]["parameters"]
    header = next(p for p in params if p["name"] == "Idempotency-Key")
    assert header["in"] == "header"
    assert header["required"] is True
