"""Вход персонала и разделы админки (DEVELOPMENT_PLAN 2.7a–b): SQLAdmin на /admin.

2.7a: без кода TOTP не войти, код второй раз не принимается; moderator не видит разделов admin;
неудачные входы ограничены лимитом; новые пароль и TOTP и `cli staff-revoke` закрывают открытые
сессии; форма, действие раздела и «Решить кейс» со страницы другого поддомена — 403 (CSRF).
8.4: секрет TOTP в БД зашифрован, строки до 8.4 и секреты под прежним ключом перешифровываются
входом и `cli staff-totp-reencrypt`. 2.7b: правка категории (и
её названия формой LocalizedText) пишет аудит и выпускает CatalogChanged (advisory lock — тот же,
что у импорта); новое стоп-слово
и регулярка действуют без перезапуска, регулярку проверяет то же, что сид в seeds-validate (RE2),
страница «Проверить правило» показывает пробу и прогон по набору; решение по кейсу — через use
case, с аудитом. Флаги, client-config, Founding и сиды поверх правки — test_admin_sections.py.

Данные коммитятся: у каждого теста свои пользователи, логины и адрес клиента (лимиты в Valkey).
"""

import secrets
from dataclasses import replace
from uuid import UUID

import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_web_container
from app.modules.identity.application.use_cases.create_staff_login import (
    CreateStaffLogin,
    CreateStaffLoginCommand,
)
from app.modules.identity.application.use_cases.reencrypt_staff_totp_secrets import (
    ReencryptStaffTotpSecrets,
    ReencryptStaffTotpSecretsCommand,
)
from app.modules.identity.application.use_cases.revoke_staff_sessions import (
    RevokeStaffSessions,
    RevokeStaffSessionsCommand,
)
from app.modules.identity.di import DEV_TOTP_KEY
from app.modules.moderation.application.ports import RuleSource
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.kernel.ids import new_id
from app.platform.security.secretbox import key_id
from app.platform.settings import Settings
from tests.plugins.admin import PASSWORD, Admin, audit_count, login, staff, stored_totp_secret
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


async def test_admin_auth_totp_secret_is_encrypted_and_legacy_rows_reencrypt_on_login(
    admin: Admin,
) -> None:
    who = await staff(admin, "admin")
    stored = await stored_totp_secret(admin, who.user_id)
    assert stored.startswith(f"v1:{key_id(DEV_TOTP_KEY)}:")
    assert who.secret not in stored
    # строка до 8.4: секрет открытым base32 — вход работает и перешифровывает её
    legacy = await staff(admin, "support")
    async with (await admin.engine()).begin() as conn:
        await conn.execute(
            text("UPDATE identity.staff_credentials SET totp_secret = :plain WHERE user_id = :id"),
            {"plain": legacy.secret, "id": legacy.user_id},
        )
    async with admin.client(_ip()) as client:
        assert await login(client, legacy) == 302
    reencrypted = await stored_totp_secret(admin, legacy.user_id)
    assert reencrypted.startswith(f"v1:{key_id(DEV_TOTP_KEY)}:")
    assert legacy.secret not in reencrypted


async def test_admin_auth_totp_key_rotation(admin: Admin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Новый APP_TOTP_KEY, прежний — в APP_TOTP_KEY_PREVIOUS (secrets-rotation.md): вход и
    `cli staff-totp-reencrypt` перешифровывают новым; чужой ключ — входа нет."""
    on_login = await staff(admin, "admin")
    by_command = await staff(admin, "support")
    lost = await staff(admin, "moderator")
    async with (await admin.engine()).begin() as conn:
        await conn.execute(
            text("UPDATE identity.staff_credentials SET totp_secret = :bad WHERE user_id = :id"),
            {"bad": "v1:00000000:" + "A" * 80, "id": lost.user_id},  # ключ, которого у нас нет
        )
    new_key = secrets.token_bytes(32)
    monkeypatch.setenv("APP_TOTP_KEY", new_key.hex())
    monkeypatch.setenv("APP_TOTP_KEY_PREVIOUS", DEV_TOTP_KEY.hex())
    settings = Settings(env_file=None)
    rotated = Admin(container=make_web_container(settings), settings=settings)
    try:
        async with rotated.client(_ip()) as client:
            assert await login(client, on_login) == 302
            assert await login(client, lost) == 400  # не расшифровать — входа нет
        assert (await stored_totp_secret(admin, on_login.user_id)).startswith(
            f"v1:{key_id(new_key)}:"
        )
        async with rotated.container() as request:
            reencrypt = await request.get(ReencryptStaffTotpSecrets)
            first = await reencrypt(ReencryptStaffTotpSecretsCommand())
            again = await reencrypt(ReencryptStaffTotpSecretsCommand())
    finally:
        await rotated.container.close()
    assert (await stored_totp_secret(admin, by_command.user_id)).startswith(
        f"v1:{key_id(new_key)}:"
    )
    assert first.reencrypted >= 1
    assert lost.user_id in first.undecryptable
    assert again.reencrypted == 0  # повтор ничего не меняет
    assert again.undecryptable == first.undecryptable


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
                "pattern": word.upper(),  # слово хранится в нижнем регистре
                "action": "flag",
                "category": "scam",
                "is_active": "y",
            },
        )
        assert created.status_code == 302, created.text[:500]
    found = (await rules.current()).check(f"prodajem {word} jeftino").action
    # база общая на прогон: лишнее правило сбило бы счёт сидов в test_moderation_seeds
    engine = await admin.container.get(AsyncEngine)
    async with engine.begin() as conn:
        deleted = await conn.scalar(
            text("DELETE FROM moderation.content_rules WHERE pattern = :word RETURNING id"),
            {"word": word},
        )
    rules.invalidate()
    assert found is not None
    assert deleted is not None
    assert await audit_count(admin, "moderation.content_rule.created", owner.user_id) == 1


REGEX = r"\bkupuj\w* tajn\S* pozornic\w*"
"""Регулярка по скелету, которой нет в сиде (строка общей базы удаляется в конце теста); `\\S` —
проверка, что админка не приводит регулярку к нижнему регистру: с `\\s` она бы не сработала."""


async def test_admin_regex_rule_is_checked_like_the_seed_and_works_without_restart(
    admin: Admin,
) -> None:
    owner = await staff(admin, "admin")
    sample = "Kupujem TAJNE pozornice, javite se"
    rules = await admin.container.get(RuleSource)
    assert (await rules.current()).check(sample).action is None
    async with admin.client(_ip()) as client:
        assert await login(client, owner) == 302
        for bad, reason in [
            (r"(\w+\s?)+kupim", "nested quantifiers"),
            (r"(?<!ne )kupim", "does not compile (RE2)"),  # `re` собрал бы, RE2 — нет
            (r"\b", "matches an empty text"),
            ("massage", "double letters"),  # в скелете двойных букв нет: «massage» — это «masage»
        ]:
            rejected = await client.post(
                "/admin/content-rule-row/create",
                data={"kind": "regex", "pattern": bad, "action": "flag", "category": "spam"},
            )
            assert rejected.status_code == 400, bad
            assert reason in rejected.text, bad
        trial = await client.post(
            "/admin/content-rule-trial",
            data={
                "kind": "regex",
                "pattern": REGEX,
                "action": "flag",
                "category": "spam",
                "sample": sample,
            },
        )
        assert trial.status_code == 200
        assert "Правило примут" in trial.text, trial.text[-800:]
        assert "kupujem tajne pozornice" in trial.text  # скелет текста пробы
        assert "сработало" in trial.text
        created = await client.post(
            "/admin/content-rule-row/create",
            data={
                "kind": "regex",
                "pattern": REGEX,
                "action": "flag",
                "category": "spam",
                "is_active": "y",
            },
        )
        assert created.status_code == 302, created.text[:500]
    verdict = (await rules.current()).check(sample)  # снимок сброшен — без перезапуска
    engine = await admin.container.get(AsyncEngine)
    async with engine.begin() as conn:
        origin = await conn.scalar(
            text(
                "DELETE FROM moderation.content_rules WHERE kind = 'regex' AND pattern = :p"
                " RETURNING origin"
            ),
            {"p": REGEX},
        )
    rules.invalidate()
    assert [m.evidence for m in verdict.matches] == [REGEX]
    assert origin == "admin"  # CHECK regex_from_seed снят (moderation_0007)
    assert await audit_count(admin, "moderation.content_rule.created", owner.user_id) == 1


async def test_admin_rule_trial_is_for_admins_only(admin: Admin) -> None:
    moderator = await staff(admin, "moderator")
    async with admin.client(_ip()) as client:
        assert await login(client, moderator) == 302
        assert "Проверить правило" not in (await client.get("/admin/")).text
        assert (await client.get("/admin/content-rule-trial")).status_code == 403


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


async def test_admin_rejects_writes_and_actions_from_other_pages(admin: Admin) -> None:
    """Cookie SameSite=Strict несёт и страница другого поддомена: форма, действие раздела (GET) и
    «Решить кейс» оттуда — 403. Своя страница, адресная строка и клиент без Fetch Metadata — как
    раньше; обычные GET-страницы не проверяются."""
    moderator = await staff(admin, "moderator")
    async with admin.container() as request:
        session = await request.get(AsyncSession)
        user = await insert_user(session, telegram_id=new_telegram_id())
        await session.commit()
    engine = await admin.engine()
    form = {"user_id": str(user), "kind": "posting_blocked", "reason_code": "spam"}
    sibling = {"Sec-Fetch-Site": "same-site"}  # Mini App или cdn на поддомене того же сайта
    foreign = {"Sec-Fetch-Site": "cross-site"}
    evil = {"Origin": "https://evil.example"}
    own = {"Sec-Fetch-Site": "same-origin", "Origin": "http://test"}

    async def restrictions() -> list[tuple[UUID, object]]:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id, lifted_at FROM identity.restrictions WHERE user_id = :id"),
                {"id": user},
            )
        return [(row.id, row.lifted_at) for row in rows]

    async with admin.client(_ip()) as client:
        assert await login(client, moderator) == 302
        for headers in (sibling, foreign, evil):
            refused = await client.post("/admin/impose-restriction", data=form, headers=headers)
            assert refused.status_code == 403, headers
        assert await restrictions() == []
        assert (await client.get("/admin/", headers=foreign)).status_code == 200  # не запись
        assert (await client.get("/admin/impose-restriction", headers=sibling)).status_code == 200
        imposed = await client.post("/admin/impose-restriction", data=form, headers=own)
        assert imposed.status_code == 200
        [(restriction, _)] = await restrictions()
        lift = "/admin/restriction-row/action/lift"
        pks = {"pks": str(restriction)}
        for headers in (sibling, foreign, evil):
            assert (await client.get(lift, params=pks, headers=headers)).status_code == 403
        dossier = await client.get(
            "/admin/decide-case", params={"case_id": str(new_id())}, headers=sibling
        )
        assert dossier.status_code == 403  # просмотр спора пишет аудит и блокирует кейс
        assert await restrictions() == [(restriction, None)]
        typed = {"Sec-Fetch-Site": "none"}  # адресная строка или закладка сотрудника
        assert (await client.get(lift, params=pks, headers=typed)).status_code == 302
    [(_, lifted_at)] = await restrictions()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo'"
                " AND args->'payload'->>'user_id' = :id"
            ),
            {"id": str(user)},
        )
    assert lifted_at is not None
    assert await audit_count(admin, "identity.restriction.imposed", moderator.user_id) == 1
    assert await audit_count(admin, "identity.restriction.lifted", moderator.user_id) == 1


async def test_admin_new_credentials_and_staff_revoke_close_open_sessions(admin: Admin) -> None:
    """Cookie подписана, но не хранится: `staff-create` заново (пароль и TOTP) и `staff-revoke`
    дают новое поколение входа — выданные раньше cookie не открывают ни /admin, ни Admin API."""
    who = await staff(admin, "admin")
    audit_log = "/admin/api/v1/audit-log"
    async with admin.client(_ip()) as old:
        assert await login(old, who) == 302
        assert (await old.get("/admin/")).status_code == 200
        assert (await old.get(audit_log)).status_code == 200
        async with admin.container() as request:
            renewed = await (await request.get(CreateStaffLogin))(
                CreateStaffLoginCommand(
                    telegram_id=who.telegram_id, login=who.login, password=PASSWORD
                )
            )
        assert renewed is not None
        assert renewed.replaced
        assert (await old.get("/admin/")).status_code == 302  # на страницу входа
        assert (await old.get(audit_log)).status_code == 401
    async with admin.client(_ip()) as client:
        assert await login(client, replace(who, secret=renewed.totp_secret)) == 302
        assert (await client.get(audit_log)).status_code == 200
        async with admin.container() as request:
            revoked = await (await request.get(RevokeStaffSessions))(
                RevokeStaffSessionsCommand(telegram_id=who.telegram_id)
            )
        assert revoked is not None
        assert not revoked.login_removed
        assert (await client.get(audit_log)).status_code == 401
        assert (await client.get("/admin/")).status_code == 302
    async with admin.container() as request:
        removed = await (await request.get(RevokeStaffSessions))(
            RevokeStaffSessionsCommand(telegram_id=who.telegram_id, remove_login=True)
        )
        missing = await (await request.get(RevokeStaffSessions))(
            RevokeStaffSessionsCommand(telegram_id=who.telegram_id)
        )
    assert removed is not None
    assert removed.login_removed
    assert missing is None  # входа больше нет
    async with admin.client(_ip()) as client:
        assert await login(client, replace(who, secret=renewed.totp_secret)) == 400
    async with (await admin.engine()).connect() as conn:
        revocations = await conn.scalar(
            text(
                "SELECT count(*) FROM platform.audit_log WHERE action ="
                " 'identity.staff.sessions_revoked' AND entity_id = :id"
            ),
            {"id": who.user_id},
        )
    assert revocations == 2
