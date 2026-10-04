"""Admin API `/admin/api/v1` (DEVELOPMENT_PLAN 2.7b, часть 1): кейсы, жалобы, карточка пользователя,
санкции, журнал аудита.

Вход — cookie со страницы /admin/login, роли перечитываются на каждый запрос; роль не та — 403,
без входа — 401 (problem+json). Меняющий запрос без `X-Requested-With: sosed-admin` или с чужого
origin — 403 `csrf_rejected`. ПД в карточке — только support и admin, и каждый просмотр — запись
`identity.user.pii_viewed`. Решения и санкции — те же use cases, что у SQLAdmin: аудит от имени
сотрудника и события (задачи подписчиков в procrastinate_jobs).

Данные коммитятся: у каждого теста свои пользователи, логины и адрес клиента (лимиты в Valkey).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.kernel.ids import CaseId, UserId, new_id
from tests.plugins.admin import Admin, Staff, audit_count, login, staff
from tests.plugins.admin import client_ip as _ip
from tests.plugins.identity import insert_user, new_telegram_id

pytestmark = pytest.mark.integration

API = "/admin/api/v1"
WRITE = {"X-Requested-With": "sosed-admin"}


@asynccontextmanager
async def _signed_in(admin: Admin, who: Staff) -> AsyncIterator[httpx.AsyncClient]:
    async with admin.client(_ip()) as client:
        assert await login(client, who) == 302
        yield client


async def _user(admin: Admin) -> UserId:
    async with admin.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session, telegram_id=new_telegram_id())
        await session.execute(
            text("UPDATE identity.users SET phone_e164 = :phone WHERE id = :id"),
            {"phone": f"+38160{new_id().int % 10_000_000:07d}", "id": user_id},
        )
        await session.commit()
    return user_id


async def _case(admin: Admin, subject: UserId) -> CaseId:
    async with admin.container() as request:
        case_id: CaseId = await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.JOB,
                entity_id=new_id(),
                subject_id=subject,
                trigger=CaseTrigger.REPORT,
                details={"signals": []},
            )
        )
    return case_id


async def _execute(admin: Admin, sql: str, **params: Any) -> None:
    async with (await admin.engine()).begin() as conn:
        await conn.execute(text(sql), params)


async def _drop_jobs(admin: Admin, user_id: UserId) -> int:
    """Задачи подписчиков событий о пользователе (решение, санкция): посчитать и убрать."""
    async with (await admin.engine()).begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
                "args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)"
            ),
            {"id": str(user_id)},
        )
    return int(result.rowcount or 0)


def _problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code


@pytest.mark.authz
async def test_authz_admin_api_needs_a_staff_session_and_the_right_role(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    support = await staff(admin, "support")
    owner = await staff(admin, "admin")
    user = await _user(admin)
    async with admin.client(_ip()) as anonymous:
        _problem(await anonymous.get(f"{API}/cases"), 401, "not_authenticated")
    async with _signed_in(admin, moderator) as client:
        listed = await client.get(f"{API}/cases")
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "no-store"
        assert "ratelimit-remaining" in listed.headers
        assert (await client.get(f"{API}/reports")).status_code == 200
        _problem(await client.get(f"{API}/audit-log"), 403, "forbidden")
        # роль снята — API закрыт сразу, без выхода: роли перечитываются на каждый запрос
        await _execute(
            admin, "DELETE FROM identity.user_roles WHERE user_id = :id", id=moderator.user_id
        )
        _problem(await client.get(f"{API}/cases"), 401, "not_authenticated")
    async with _signed_in(admin, support) as client:
        assert (await client.get(f"{API}/users/{user}")).status_code == 200
        _problem(await client.get(f"{API}/cases"), 403, "forbidden")
        _problem(await client.get(f"{API}/reports"), 403, "forbidden")
        _problem(await client.get(f"{API}/audit-log"), 403, "forbidden")
        imposed = await client.post(
            f"{API}/users/{user}/restrictions",
            json={"kind": "posting_blocked", "reason_code": "spam"},
            headers=WRITE,
        )
        _problem(imposed, 403, "forbidden")
    async with _signed_in(admin, owner) as client:
        for path in ("/cases", "/reports", "/audit-log", f"/users/{user}"):
            assert (await client.get(f"{API}{path}")).status_code == 200, path


@pytest.mark.authz
async def test_authz_admin_api_rejects_cross_site_writes(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    case_id = await _case(admin, await _user(admin))
    take = f"{API}/cases/{case_id}/take"
    async with _signed_in(admin, moderator) as client:
        _problem(await client.post(take), 403, "csrf_rejected")
        evil = {**WRITE, "Origin": "https://evil.example"}
        _problem(await client.post(take, headers=evil), 403, "csrf_rejected")
        sibling = {**WRITE, "Sec-Fetch-Site": "same-site"}  # другой поддомен того же сайта
        _problem(await client.post(take, headers=sibling), 403, "csrf_rejected")
        own = {**WRITE, "Origin": "http://test", "Sec-Fetch-Site": "same-origin"}
        taken = await client.post(take, headers=own)
        assert taken.status_code == 200, taken.text
        assert taken.json()["status"] == "in_review"
        assert taken.json()["assigned_to"] == str(moderator.user_id)
    assert await audit_count(admin, "moderation.case.taken", moderator.user_id) == 1


@pytest.mark.authz
async def test_authz_personal_data_only_for_support_and_admin_and_every_view_is_audited(
    admin: Admin,
) -> None:
    moderator = await staff(admin, "moderator")
    support = await staff(admin, "support")
    owner = await staff(admin, "admin")
    user = await _user(admin)
    case_id = await _case(admin, user)
    async with _signed_in(admin, moderator) as client:
        card = (await client.get(f"{API}/users/{user}")).json()
        assert card["personal_data"] is None  # moderator решает без ПД
        assert card["activity"]["completed_deals"] == 0
    assert await audit_count(admin, "identity.user.pii_viewed", moderator.user_id) == 0
    async with _signed_in(admin, support) as client:
        first = (await client.get(f"{API}/users/{user}")).json()
        assert first["personal_data"]["display_name"] == "Ana"
        assert first["personal_data"]["phone_e164"].startswith("+38160")
        assert first["personal_data"]["telegram_id"] is not None
        second = await client.get(f"{API}/users/{user}", params={"case_id": str(case_id)})
        assert second.status_code == 200
        _problem(await client.get(f"{API}/users/{new_id()}"), 404, "user_not_found")
    assert await audit_count(admin, "identity.user.pii_viewed", support.user_id) == 2
    async with _signed_in(admin, owner) as client:
        page = await client.get(
            f"{API}/audit-log",
            params={"action": "identity.user", "actor_id": str(support.user_id), "limit": 1},
        )
        assert page.status_code == 200
        body = page.json()
        assert [item["action"] for item in body["items"]] == ["identity.user.pii_viewed"]
        assert body["items"][0]["changes"]["case_id"] == str(case_id)  # новые первыми
        assert body["items"][0]["entity_id"] == str(user)
        rest = await client.get(
            f"{API}/audit-log",
            params={
                "action": "identity.user",
                "actor_id": str(support.user_id),
                "cursor": body["next_cursor"],
            },
        )
        assert [item["changes"]["case_id"] for item in rest.json()["items"]] == [None]
        assert rest.json()["next_cursor"] is None
        _problem(
            await client.get(f"{API}/audit-log", params={"cursor": "garbage"}),
            422,
            "invalid_cursor",
        )


@pytest.mark.authz
async def test_authz_cases_are_taken_decided_and_escalated_through_use_cases(
    admin_with_storage: Admin,
) -> None:
    admin = admin_with_storage  # спорам нужен фасад media (ссылки на фото доказательств)
    moderator = await staff(admin, "moderator")
    author = await _user(admin)
    first, second = await _case(admin, author), await _case(admin, author)
    async with _signed_in(admin, moderator) as client:
        queue = await client.get(
            f"{API}/cases", params={"queue": "fraud", "subject_id": str(author), "limit": 1}
        )
        assert [item["id"] for item in queue.json()["items"]] == [str(first)]  # ближний срок
        more = await client.get(
            f"{API}/cases",
            params={
                "queue": "fraud",
                "subject_id": str(author),
                "cursor": queue.json()["next_cursor"],
            },
        )
        assert [item["id"] for item in more.json()["items"]] == [str(second)]
        recent = await client.get(
            f"{API}/cases",
            params={
                "subject_id": str(author),
                "order": "recent",
                "cursor": queue.json()["next_cursor"],
            },
        )
        _problem(recent, 422, "invalid_cursor")  # курсор другого порядка
        assert (await client.post(f"{API}/cases/{first}/take", headers=WRITE)).status_code == 200
        decided = await client.post(
            f"{API}/cases/{first}/decide",
            json={"verdict": "rejected", "reason_code": "prepayment_scam", "severity": "serious"},
            headers=WRITE,
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "rejected"
        assert decided.json()["sanction"] == "suspension"
        assert decided.json()["restriction_id"] is not None
        again = await client.post(
            f"{API}/cases/{first}/decide", json={"verdict": "approved"}, headers=WRITE
        )
        _problem(again, 409, "case_state_conflict")
        escalated = await client.post(
            f"{API}/cases/{second}/escalate", json={"note": "нужен старший"}, headers=WRITE
        )
        assert escalated.json()["status"] == "escalated"
        assert escalated.json()["notes"] == "нужен старший"
        # спор так не решить, и обычный кейс — не спор
        _problem(await client.get(f"{API}/cases/{second}/dispute"), 409, "case_kind_conflict")
        resolve = await client.post(
            f"{API}/cases/{second}/resolve-dispute",
            json={"outcome": "completed", "reason_code": "work_done"},
            headers=WRITE,
        )
        _problem(resolve, 409, "case_kind_conflict")
        _problem(await client.get(f"{API}/cases/{new_id()}"), 404, "case_not_found")
        card = (await client.get(f"{API}/cases/{first}")).json()
        assert card["decided_by"] == str(moderator.user_id)
    assert await audit_count(admin, "moderation.case.decided", moderator.user_id) == 1
    assert await audit_count(admin, "moderation.case.escalated", moderator.user_id) == 1
    # решение и санкция выпустили события: statement of reasons и уведомление о санкции
    assert await _drop_jobs(admin, author) >= 2


@pytest.mark.authz
async def test_authz_restrictions_are_imposed_and_lifted_through_use_cases(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    user, other = await _user(admin), await _user(admin)
    async with _signed_in(admin, moderator) as client:
        imposed = await client.post(
            f"{API}/users/{user}/restrictions",
            json={"kind": "posting_blocked", "reason_code": "spam"},
            headers=WRITE,
        )
        assert imposed.status_code == 201, imposed.text
        restriction = imposed.json()["id"]
        bad = await client.post(
            f"{API}/users/{user}/restrictions",
            json={"kind": "posting_blocked", "reason_code": "Spam!"},
            headers=WRITE,
        )
        _problem(bad, 422, "invalid_restriction")
        card = (await client.get(f"{API}/users/{user}")).json()
        assert [item["id"] for item in card["restrictions"]] == [restriction]
        assert card["trust_level"] == 0
        assert await _drop_jobs(admin, user) >= 1  # UserRestricted
        foreign = await client.post(
            f"{API}/users/{other}/restrictions/{restriction}/lift", headers=WRITE
        )
        _problem(foreign, 404, "restriction_not_found")  # чужая санкция по пути другого
        lifted = await client.post(
            f"{API}/users/{user}/restrictions/{restriction}/lift", headers=WRITE
        )
        assert lifted.status_code == 204
        twice = await client.post(
            f"{API}/users/{user}/restrictions/{restriction}/lift", headers=WRITE
        )
        _problem(twice, 404, "restriction_not_found")
        card = (await client.get(f"{API}/users/{user}")).json()
        assert card["restrictions"][0]["lifted_at"] is not None
    assert await audit_count(admin, "identity.restriction.imposed", moderator.user_id) == 1
    assert await audit_count(admin, "identity.restriction.lifted", moderator.user_id) == 1
    assert await _drop_jobs(admin, user) >= 1  # UserRestrictionsLifted → поиск вернёт профиль


@pytest.mark.authz
async def test_authz_reports_are_listed_and_read(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    reporter, author = await _user(admin), await _user(admin)
    case_id = await _case(admin, author)
    report_id = new_id()
    await _execute(
        admin,
        "INSERT INTO moderation.reports (id, reporter_id, target_type, target_id, reason, comment,"
        " case_id) VALUES (:id, :reporter, 'job', :target, 'fraud', 'просит предоплату', :case)",
        id=report_id,
        reporter=reporter,
        target=new_id(),
        case=case_id,
    )
    async with _signed_in(admin, moderator) as client:
        listed = await client.get(f"{API}/reports", params={"case_id": str(case_id)})
        assert [item["id"] for item in listed.json()["items"]] == [str(report_id)]
        by_reporter = await client.get(
            f"{API}/reports", params={"reporter_id": str(reporter), "status": "open"}
        )
        assert [item["id"] for item in by_reporter.json()["items"]] == [str(report_id)]
        report = await client.get(f"{API}/reports/{report_id}")
        assert report.status_code == 200
        assert report.json()["comment"] == "просит предоплату"
        assert UUID(report.json()["case_id"]) == case_id
        _problem(await client.get(f"{API}/reports/{new_id()}"), 404, "report_not_found")
