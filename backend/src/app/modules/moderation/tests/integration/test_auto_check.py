"""Конвейер автомодерации (DEVELOPMENT_PLAN 2.6): тестовая цель на фейках проходит все ветки.

Правила — настоящий ContentRulesChecker на словаре теста, AI — фейки с заданным ответом,
кейсы и журнал — PostgreSQL в откатываемой транзакции.
"""

from datetime import timedelta
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from app.modules.moderation.application.use_cases.auto_check import (
    SAMPLE_RATE_FLAG,
    AutoCheckCommand,
)
from app.modules.moderation.application.use_cases.decide_case import DecideCaseCommand
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route
from app.modules.moderation.domain.rules import ContentRule, RuleAction, RuleCategory, RuleKind
from app.platform.ai.port import ContentKind, Unavailable, UnavailableReason
from app.platform.ai.stubs import NO_KEY
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import UserId, new_id

from .conftest import Moderation

pytestmark = pytest.mark.integration

COCAINE = ContentRule(
    pattern="kokain*", kind=RuleKind.WORD, action=RuleAction.FLAG, category=RuleCategory.DRUGS
)
COURIER = ContentRule(
    pattern="закладчик*", kind=RuleKind.WORD, action=RuleAction.BLOCK, category=RuleCategory.DRUGS
)
EASY_MONEY = ContentRule(
    pattern="pasivni prihod", kind=RuleKind.WORD, action=RuleAction.FLAG, category=RuleCategory.SPAM
)


async def check_job(
    moderation: Moderation, author: UserId, text: str, *, edit: bool = False
) -> tuple[UUID, Route | None]:
    job = moderation.jobs.add(author, text)
    routing = await moderation.auto_check(
        AutoCheckCommand(entity_type=EntityType.JOB, entity_id=job, author_id=author, edit=edit)
    )
    return job, routing.route if routing else None


async def cases_of(moderation: Moderation, entity: UUID) -> list[tuple[object, ...]]:
    return await moderation.rows(
        "SELECT queue, trigger, status, evidence->0->'signals' FROM moderation.cases"
        " WHERE entity_id = :id",
        id=entity,
    )


async def test_clean_text_is_published(moderation: Moderation) -> None:
    author = await moderation.user(trust_level=1)

    job, route = await check_job(moderation, author, "Нужно повесить три полки в Лиманe")

    assert route is Route.PUBLISH
    assert moderation.jobs.published == [(job, 1)]  # версия, которую проверяли
    assert moderation.jobs.auto_published == [job]
    assert await cases_of(moderation, job) == []
    assert moderation.classifier.calls == 0  # уровень 1 без флагов — без классификатора
    assert moderation.metrics.routes == [(EntityType.JOB, Route.PUBLISH)]
    [(action, changes)] = await moderation.rows(
        "SELECT action, changes->>'route' FROM platform.audit_log WHERE entity_id = :id", id=job
    )
    assert (action, changes) == ("moderation.auto_check", "publish")


async def test_stop_word_waits_in_the_queue_of_its_category(moderation: Moderation) -> None:
    moderation.rules.rules = (COCAINE, EASY_MONEY)
    author = await moderation.user()

    spam, spam_route = await check_job(moderation, author, "Pasivni prihod od kuće!")
    drugs, drugs_route = await check_job(moderation, author, "Prodajem kokain, dostava")

    assert (spam_route, drugs_route) == (Route.REVIEW, Route.REVIEW)
    assert moderation.jobs.published == []
    assert await cases_of(moderation, spam) == [
        ("premod", "new_content", "pending", ["rule:spam:flag:pasivni prihod"])
    ]
    [(queue, *_)] = await cases_of(moderation, drugs)
    assert queue == "safety"  # наркотики — очередь P0, даже когда слово только флаг (§14.2)


async def test_visible_message_is_hidden_only_for_a_violation(moderation: Moderation) -> None:
    """Сообщение чата видно сразу (6.3a): нарушение прячет его до решения, одобрение возвращает;
    сомнение (AI недоступен) — кейс для человека, но сообщение остаётся видно."""
    moderation.rules.rules = (EASY_MONEY,)
    author = await moderation.user(trust_level=1)

    async def check(text: str) -> UUID:
        message = moderation.jobs.add(author, text, kind=ContentKind.MESSAGE, visible=True)
        await moderation.auto_check(
            AutoCheckCommand(entity_type=EntityType.JOB, entity_id=message, author_id=author)
        )
        return message

    flagged = await check("Pasivni prihod od kuće!")
    clean = await check("Буду в 19:00")
    moderation.omni.result = Unavailable(UnavailableReason.PROVIDER_ERROR)
    doubtful = await check("Захвачу стремянку")

    assert moderation.jobs.hidden == [(flagged, "other")]
    assert moderation.jobs.published == [(clean, 1)]
    cases = {view.entity_id: view.id for view in await moderation.queries.open_cases()}
    assert set(cases) == {flagged, doubtful}
    await moderation.decide(
        DecideCaseCommand(case_id=cases[flagged], verdict=ModerationDecision.APPROVED)
    )
    # одобрение — версии, которую показала карточка кейса (ADV-11)
    assert moderation.jobs.published == [(clean, 1), (flagged, 1)]


async def test_ai_failure_goes_to_p2(moderation: Moderation) -> None:
    """С ключом проверку ждали, а она не состоялась (сеть, 5xx), — решает человек."""
    moderation.omni.result = Unavailable(UnavailableReason.PROVIDER_ERROR)
    author = await moderation.user(trust_level=1)

    job, route = await check_job(moderation, author, "Ремонт стиральных машин", edit=True)

    assert route is Route.REVIEW
    [(queue, trigger, status, signals)] = await cases_of(moderation, job)
    assert (queue, trigger, status) == ("premod", "edit", "pending")
    assert signals == ["omni:unavailable:provider_error"]


async def test_without_ai_keys_text_is_judged_by_stop_rules(moderation: Moderation) -> None:
    """MVP без ключей AI (K25, K26 — после MVP): адаптеры отвечают «ключа нет», чистая заявка
    новичка публикуется сразу и без кейса, стоп-слово по-прежнему ведёт к модератору."""
    moderation.omni.result = NO_KEY
    moderation.classifier.verdict = NO_KEY
    moderation.flags.values[SAMPLE_RATE_FLAG] = 0.0  # без выборки: кейс дал бы только сигнал
    moderation.rules.rules = (EASY_MONEY,)
    newcomer = await moderation.user()  # уровень 0 — классификатор зовут

    clean, clean_route = await check_job(moderation, newcomer, "Нужно повесить люстру")
    spam, spam_route = await check_job(moderation, newcomer, "Pasivni prihod od kuće!")

    assert (clean_route, spam_route) == (Route.PUBLISH, Route.REVIEW)
    assert moderation.jobs.published == [(clean, 1)]
    assert moderation.classifier.calls == 2
    assert await cases_of(moderation, clean) == []
    assert await cases_of(moderation, spam) == [
        ("premod", "new_content", "pending", ["rule:spam:flag:pasivni prihod"])
    ]


async def test_without_ai_keys_chat_message_opens_no_case(moderation: Moderation) -> None:
    """Сообщение чата без ключей AI: чистое остаётся видно и кейса не открывает; выборка
    новичков (страховка) — та же, что с ключами."""
    moderation.omni.result = NO_KEY
    moderation.classifier.verdict = NO_KEY
    moderation.flags.values[SAMPLE_RATE_FLAG] = 0.0
    newcomer = await moderation.user()

    async def check(text: str) -> UUID:
        message = moderation.jobs.add(newcomer, text, kind=ContentKind.MESSAGE, visible=True)
        routing = await moderation.auto_check(
            AutoCheckCommand(entity_type=EntityType.JOB, entity_id=message, author_id=newcomer)
        )
        assert routing is not None
        assert routing.route is Route.PUBLISH
        return message

    quiet = await check("Буду в 19:00, захвачу стремянку")
    moderation.flags.values[SAMPLE_RATE_FLAG] = 1.0
    sampled = await check("Спасибо, до завтра")

    assert moderation.jobs.hidden == []
    assert await cases_of(moderation, quiet) == []
    assert await cases_of(moderation, sampled) == [("premod", "auto_flag", "pending", ["sample"])]


async def test_p0_is_hidden_and_the_account_frozen(moderation: Moderation) -> None:
    moderation.rules.rules = (COURIER,)
    author = await moderation.user()

    job, route = await check_job(moderation, author, "Ищем закладчиков, оплата каждый день")

    assert route is Route.BLOCK
    assert moderation.jobs.hidden == [(job, "drug_courier")]
    [(queue, trigger, status, _)] = await cases_of(moderation, job)
    assert (queue, trigger, status) == ("safety", "auto_flag", "pending")
    [freeze] = moderation.identity.restricted
    assert (freeze.user_id, freeze.kind, freeze.reason_code) == (
        author,
        RestrictionKind.SUSPENDED,
        "drug_courier",
    )
    assert freeze.case_id is not None


async def test_level_zero_sample_is_reviewed_after_publication(moderation: Moderation) -> None:
    moderation.flags.values[SAMPLE_RATE_FLAG] = 1.0  # каждая публикация — в выборку
    newcomer = await moderation.user()

    job, route = await check_job(moderation, newcomer, "Нужна уборка после ремонта")

    assert route is Route.PUBLISH
    assert moderation.jobs.published == [(job, 1)]
    assert await cases_of(moderation, job) == [("premod", "auto_flag", "pending", ["sample"])]


async def test_new_profiles_always_wait_for_a_human(moderation: Moderation) -> None:
    author = await moderation.user(trust_level=2)
    profile = moderation.profiles.add(
        author, "Электрик, 10 лет опыта", kind=ContentKind.PROFILE, always_review=True
    )

    routing = await moderation.auto_check(
        AutoCheckCommand(entity_type=EntityType.PROFILE, entity_id=profile, author_id=author)
    )

    assert routing is not None
    assert routing.route is Route.REVIEW
    assert moderation.profiles.published == []


async def test_moderator_decision_publishes_or_hides(moderation: Moderation) -> None:
    moderation.omni.result = Unavailable(UnavailableReason.PROVIDER_ERROR)
    author = await moderation.user(trust_level=1)
    approved, _ = await check_job(moderation, author, "Покраска забора")
    rejected, _ = await check_job(moderation, author, "Покраска забора, предоплата 50%")
    open_cases = {view.entity_id: view.id for view in await moderation.queries.open_cases()}

    await moderation.decide(
        DecideCaseCommand(case_id=open_cases[approved], verdict=ModerationDecision.APPROVED)
    )
    await moderation.decide(
        DecideCaseCommand(
            case_id=open_cases[rejected],
            verdict=ModerationDecision.REJECTED,
            reason_code="prepayment_scam",
        )
    )

    assert moderation.jobs.published == [(approved, 1)]  # версия из карточки кейса (ADV-11)
    assert moderation.jobs.auto_published == []  # решение модератора, а не автопроверка
    assert moderation.jobs.hidden == [(rejected, "prepayment_scam")]
    assert moderation.identity.lifted == [open_cases[approved]]  # заморозка автопроверки


async def test_open_cases_are_listed_by_deadline(moderation: Moderation) -> None:
    moderation.rules.rules = (EASY_MONEY, COURIER)
    author = await moderation.user()
    premod, _ = await check_job(moderation, author, "pasivni prihod")
    safety, _ = await check_job(moderation, author, "закладчик")

    views = [v for v in await moderation.queries.open_cases() if v.entity_id in {premod, safety}]

    assert [v.entity_id for v in views] == [premod, safety]  # P2 — 30 минут, P0 — час
    assert views[1].signals == ("rule:drugs:block:закладчик*",)
    assert views[0].due_at - moderation.clock.now() == timedelta(minutes=30)


async def test_missing_target_or_object_is_skipped(moderation: Moderation) -> None:
    author = await moderation.user()

    with capture_logs() as logs:
        missing = await moderation.auto_check(
            AutoCheckCommand(entity_type=EntityType.MESSAGE, entity_id=new_id(), author_id=author)
        )
    gone = await moderation.auto_check(
        AutoCheckCommand(entity_type=EntityType.JOB, entity_id=new_id(), author_id=author)
    )

    assert (missing, gone) == (None, None)
    assert [e["event"] for e in logs] == ["moderation_target_missing"]
