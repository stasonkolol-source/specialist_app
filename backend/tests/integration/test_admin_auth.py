"""Вход персонала и разделы админки (DEVELOPMENT_PLAN 2.7a–b): SQLAdmin на /admin.

2.7a: без кода TOTP не войти, код второй раз не принимается; moderator не видит разделов admin;
неудачные входы ограничены лимитом. 2.7b: правка категории (и её названия формой LocalizedText)
пишет аудит и выпускает CatalogChanged (advisory lock — тот же, что у импорта); новое стоп-слово
действует без перезапуска; регулярку из админки не завести; решение по кейсу — через use case, с
аудитом. Флаги, client-config, Founding и сиды поверх правки — test_admin_sections.py.

Данные коммитятся: у каждого теста свои пользователи, логины и адрес клиента (лимиты в Valkey).
"""

from uuid import UUID

import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.moderation.application.ports import RuleSource
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.kernel.ids import new_id
from tests.plugins.admin import Admin, audit_count, login, staff
from tests.plugins.admin import client_ip as _ip
from tests.plugins.identity import insert_user, new_telegram_id

pytestmark = pytest.mark.integration


async def test_admin_auth_requires_totp_and_rejects_replay(admin: Admin) -> None:
    who = await staff(admin, "admin")
    async with admin.client(_ip()) as client:
        assert (await client.get("/admin/")).status_code == 302  # без входа — на страницу входа
        assert await login(client, who, code="") == 400
        assert await login(client, who, code="000000") in {400}
        code = pyotp.TOTP(who.secret).now()
        assert await login(client, who, code=code) == 302
        assert (await client.get("/admin/")).status_code == 200
    async with admin.client(_ip()) as other:
        assert await login(other, who, code=code) == 400  # тот же код второй раз не входит
    assert await audit_count(admin, "identity.staff.login", who.user_id) == 1


async def test_admin_auth_moderator_does_not_see_admin_sections(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    owner = await staff(admin, "admin")
    async with admin.client(_ip()) as client:
        assert await login(client, moderator) == 302
        index = (await client.get("/admin/")).text
        assert "Кейсы" in index
        assert "Контент-правила" not in index
        assert "Журнал аудита" not in index
        assert "Категории" not in index
        assert (await client.get("/admin/content-rule-row/list")).status_code == 403
        assert (await client.get("/admin/audit-record/list")).status_code == 403
        assert (await client.get("/admin/case-row/list")).status_code == 200
    async with admin.client(_ip()) as client:
        assert await login(client, owner) == 302
        index = (await client.get("/admin/")).text
        assert "Контент-правила" in index
        assert "Журнал аудита" in index
        assert (await client.get("/admin/content-rule-row/list")).status_code == 200


async def test_admin_auth_failed_logins_are_limited(admin: Admin) -> None:
    who = await staff(admin, "support")
    async with admin.client(_ip()) as client:
        for _ in range(5):
            assert await login(client, who, code="123456") == 400
        # лимит на логин: даже верные данные — 429, пока окно не пройдёт
        assert await login(client, who) == 429
    async with admin.client(_ip()) as client:
        assert await login(client, who) == 429  # с другого адреса — тот же логин закрыт


async def test_admin_category_edit_is_audited_and_emits_catalog_changed(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    async with admin.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        category_id = await conn.scalar(
            text(
                "INSERT INTO catalog.categories (slug, name) VALUES"
                ' (:slug, \'{"ru": "Тест", "sr-Cyrl": "Тест"}\') RETURNING id'
            ),
            {"slug": f"admin-test-{new_id().hex[:8]}"},
        )
    async with admin.client(_ip()) as client:
        assert await login(client, owner) == 302
        form = await client.get(f"/admin/category-row/edit/{category_id}")
        assert 'value="Тест"' in form.text  # название развёрнуто в поля локалей
        edited = await client.post(
            f"/admin/category-row/edit/{category_id}",
            data={
                "jobs_enabled": "y",
                "max_responses": "3",
                "risk_level": "1",
                "sort_order": "0",
                "name_ru": "Тест правка",
                "name_sr_cyrl": "Тест",
                "name_sr_latn": "",
                "name_en": "",
            },
        )
        assert edited.status_code == 302, edited.text[:500]
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT is_active, max_responses, name, name_origin FROM catalog.categories"
                    " WHERE id = :id"
                ),
                {"id": category_id},
            )
        ).one()
        jobs = await conn.scalar(
            text(
                "DELETE FROM procrastinate_jobs WHERE task_name = 'search.on_catalog_changed'"
                " AND status = 'todo' AND args->'payload'->'category_ids' @> jsonb_build_array("
                "CAST(:id AS integer)) RETURNING 1"
            ),
            {"id": category_id},
        )
    # база общая на прогон: лишний раздел сбил бы счёт сидов в test_catalog_seeds
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM catalog.categories WHERE id = :id"), {"id": category_id}
        )
    assert (row.is_active, row.max_responses) == (False, 3)
    # пустая латиница — транслит кириллицы; название теперь ведёт админка
    assert row.name == {"ru": "Тест правка", "sr-Cyrl": "Тест", "sr-Latn": "Test"}
    assert row.name_origin == "admin"
    assert jobs == 1
    assert await audit_count(admin, "catalog.category.updated", owner.user_id) == 1


async def test_admin_stop_word_works_without_restart(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    word = f"zabranjeno{new_id().hex[:6]}"
    rules = await admin.container.get(RuleSource)
    assert (await rules.current()).check(f"prodajem {word} jeftino").action is None
    async with admin.client(_ip()) as client:
        assert await login(client, owner) == 302
        created = await client.post(
            "/admin/content-rule-row/create",
            data={
                "kind": "word",
                "pattern": word,
                "action": "flag",
                "category": "scam",
                "is_active": "y",
            },
        )
        assert created.status_code == 302, created.text[:500]
        regex = await client.post(
            "/admin/content-rule-row/create",
            data={"kind": "regex", "pattern": "a+b", "action": "flag", "category": "scam"},
        )
        assert regex.status_code == 400  # регулярки — только из сида
    found = (await rules.current()).check(f"prodajem {word} jeftino").action
    # база общая на прогон: лишнее правило сбило бы счёт сидов в test_moderation_seeds
    engine = await admin.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM moderation.content_rules WHERE pattern = :word"), {"word": word}
        )
    rules.invalidate()
    assert found is not None
    assert await audit_count(admin, "moderation.content_rule.created", owner.user_id) == 1


async def test_admin_case_is_decided_through_use_case(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    async with admin.container() as request:
        session = await request.get(AsyncSession)
        author = await insert_user(session, telegram_id=new_telegram_id())
        await session.commit()
    async with admin.container() as request:
        case_id = await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.JOB,
                entity_id=new_id(),
                subject_id=author,
                trigger=CaseTrigger.REPORT,
                details={"signals": []},
            )
        )
    async with admin.client(_ip()) as client:
        assert await login(client, moderator) == 302
        page = await client.get("/admin/decide-case", params={"case_id": str(case_id)})
        assert page.status_code == 200
        decided = await client.post(
            "/admin/decide-case",
            data={
                "case_id": str(case_id),
                "verdict": "rejected",
                "reason_code": "prepayment_scam",
                "severity": "serious",
            },
        )
        assert decided.status_code == 200
        assert "rejected, sanction suspension" in decided.text, decided.text[-800:]
    async with admin.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM moderation.cases WHERE id = :id"), {"id": case_id}
        )
        decided_by = await conn.scalar(
            text("SELECT decided_by FROM moderation.cases WHERE id = :id"), {"id": case_id}
        )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
                "args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)"
            ),
            {"id": str(author)},
        )
    assert status == "rejected"
    assert UUID(str(decided_by)) == moderator.user_id
