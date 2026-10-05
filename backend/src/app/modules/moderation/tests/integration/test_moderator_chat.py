"""Чат модераторов (DEVELOPMENT_PLAN 2.5b) на фейковых Update: карточка нового кейса уходит в чат
`TELEGRAM_MODERATORS_CHAT_ID`; кнопку без роли модератора бот отклоняет ответом, кейс не
меняется; «Одобрить», «Отклонить с причиной» (причина → тяжесть) и «Эскалировать» вызывают
DecideCase и EscalateCase, карточка дописывает итог и кто решил; апелляция с карточки снимает
санкцию. Id чата модераторов (K29): `/chatid`, `/start@<бот>`, добавление бота в группу и переход
в супергруппу — ответ только персоналу, настроенный чат бот узнаёт. Bot API — запись вызовов, БД
и Valkey — настоящие.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, Message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.bot import BotHarness, bot_harness

from app.modules.moderation.application.use_cases.file_appeal import (
    FileAppeal,
    FileAppealCommand,
)
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.application.use_cases.post_case_card import (
    PostCaseCard,
    PostCaseCardCommand,
)
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.tests.integration.test_appeals import close_cases
from app.platform.kernel.ids import CaseId, UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback

pytestmark = pytest.mark.integration

CHAT = -1_001_234_567_890
GROUP = -1_009_876_543_210
"""Группа, которая ещё не чат модераторов (id — как у супергрупп, `-100…`)."""
SENT_AT = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


USERS: list[UserId] = []
"""Пользователи теста: данные коммитятся, в конце их открытые кейсы закрываются."""


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch, TELEGRAM_MODERATORS_CHAT_ID=str(CHAT)) as harness:
        yield harness
        await close_cases(harness.container, USERS)
        USERS.clear()


def telegram_user() -> int:
    return 7_000_000_000 + new_id().int % 1_000_000_000


async def sql(harness: BotHarness, statement: str, **params: object) -> Any:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return result.first() if result.returns_rows else None


async def user_of(harness: BotHarness, telegram_id: int) -> UserId:
    await harness.send(telegram_id, "/start")
    found = await sql(
        harness,
        "SELECT user_id FROM identity.auth_identities WHERE provider = 'telegram'"
        " AND subject = :tg",
        tg=str(telegram_id),
    )
    USERS.append(UserId(found.user_id))
    return UserId(found.user_id)


async def moderator(harness: BotHarness) -> int:
    telegram_id = telegram_user()
    user_id = await user_of(harness, telegram_id)
    await sql(
        harness,
        "INSERT INTO identity.user_roles (user_id, role) VALUES (:id, 'moderator')",
        id=user_id,
    )
    return telegram_id


async def open_case(harness: BotHarness, subject: UserId) -> CaseId:
    async with harness.container() as request:
        return await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.USER,
                entity_id=subject,
                subject_id=subject,
                trigger=CaseTrigger.AUTO_FLAG,
                details={"signals": ["demo"]},
            )
        )


async def case_row(harness: BotHarness, case_id: CaseId) -> Any:
    return await sql(
        harness,
        "SELECT status, reason_code, decided_by FROM moderation.cases WHERE id = :id",
        id=case_id,
    )


def press(action: CallbackAction, case_id: CaseId, arg: str | None = None) -> str:
    return encode_callback(CallbackData(action, case_id, arg))


def edits(calls: list[TelegramMethod[Any]]) -> list[str]:
    return [call.text or "" for call in calls if isinstance(call, EditMessageText)]


def alerts(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, AnswerCallbackQuery)]


async def test_new_case_card_goes_to_the_moderators_chat(harness: BotHarness) -> None:
    subject = await user_of(harness, telegram_user())
    case_id = await open_case(harness, subject)
    before = len(harness.session.calls)

    async with harness.container() as request:
        posted = await (await request.get(PostCaseCard))(PostCaseCardCommand(case_id=case_id))

    [card] = [c for c in harness.session.calls[before:] if isinstance(c, SendMessage)]
    assert posted
    assert card.chat_id == CHAT
    assert "P1 · Мошенничество" in card.text
    assert str(case_id) in card.text
    assert "demo" in card.text
    buttons = [b.text for row in card.reply_markup.inline_keyboard for b in row]  # type: ignore[union-attr]
    assert buttons == ["Одобрить", "Отклонить с причиной", "Эскалировать"]


async def test_press_without_role_is_answered_and_ignored(harness: BotHarness) -> None:
    stranger = telegram_user()
    subject = await user_of(harness, telegram_user())
    await user_of(harness, stranger)
    case_id = await open_case(harness, subject)

    calls = await harness.press(stranger, press(CallbackAction.CASE_APPROVE, case_id))
    unknown = await harness.press(telegram_user(), press(CallbackAction.CASE_APPROVE, case_id))

    expected = "Решать кейсы могут только модераторы. Роль выдаёт администратор."
    assert alerts(calls) == [expected]
    assert alerts(unknown) == [expected]  # не пользователь «Соседей» вовсе
    assert edits(calls) == []
    assert (await case_row(harness, case_id)).status == "pending"


async def test_reject_with_reason_and_severity_decides_the_case(harness: BotHarness) -> None:
    mod = await moderator(harness)
    subject = await user_of(harness, telegram_user())
    case_id = await open_case(harness, subject)

    picker = await harness.press(mod, press(CallbackAction.CASE_REJECT, case_id))
    severity = await harness.press(mod, press(CallbackAction.CASE_REJECT, case_id, "spam_ad"))
    decided = await harness.press(mod, press(CallbackAction.CASE_SANCTION, case_id, "mspam_ad"))

    assert [type(c) for c in picker if not isinstance(c, AnswerCallbackQuery)] == [
        EditMessageReplyMarkup
    ]
    assert [type(c) for c in severity if not isinstance(c, AnswerCallbackQuery)] == [
        EditMessageReplyMarkup
    ]
    [card] = edits(decided)
    assert card.endswith("⛔ Нарушение: spam_ad, санкция: warning — Ana")
    row = await case_row(harness, case_id)
    assert (row.status, row.reason_code) == ("rejected", "spam_ad")
    assert row.decided_by is not None
    notice = await sql(
        harness,
        "SELECT count(*) AS n FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.notify_moderation_decision' AND args->'payload'->>'author_id' = :user",
        user=str(subject),
    )
    assert notice.n == 1  # решение доходит до пользователя, как из cli


async def test_approve_and_escalate(harness: BotHarness) -> None:
    mod = await moderator(harness)
    subject = await user_of(harness, telegram_user())
    approved = await open_case(harness, subject)
    escalated = await open_case(harness, await user_of(harness, telegram_user()))

    first = await harness.press(mod, press(CallbackAction.CASE_APPROVE, approved))
    second = await harness.press(mod, press(CallbackAction.CASE_ESCALATE, escalated))
    late = await harness.press(mod, press(CallbackAction.CASE_APPROVE, approved))

    assert edits(first)[0].endswith("✅ Одобрено — Ana")
    assert edits(second)[0].endswith("⬆️ Эскалировано — Ana")
    assert (await case_row(harness, approved)).status == "approved"
    assert (await case_row(harness, escalated)).status == "escalated"
    assert edits(late) == []  # решённый кейс не решают снова: ответ ошибкой
    assert len(alerts(late)) == 1


async def test_appeal_card_grants_the_appeal(harness: BotHarness) -> None:
    mod = await moderator(harness)
    subject = await user_of(harness, telegram_user())
    decision = await open_case(harness, subject)
    await harness.press(mod, press(CallbackAction.CASE_SANCTION, decision, "sspam_ad"))
    async with harness.container() as request:
        filed = await (await request.get(FileAppeal))(FileAppealCommand(user_id=subject))

    granted = await harness.press(mod, press(CallbackAction.CASE_APPROVE, filed.appeal.id))

    assert edits(granted)[0].endswith("✅ Апелляция удовлетворена, санкция снята — Ana")
    lifted = await sql(
        harness,
        "SELECT lifted_at FROM identity.restrictions WHERE case_id = :id",
        id=decision,
    )
    assert lifted.lifted_at is not None


def group(chat_id: int = GROUP) -> Chat:
    return Chat(id=chat_id, type="supergroup", title="Модерация dev")


def in_group(
    text_value: str | None = None, *, chat_id: int = GROUP, migrate_from_chat_id: int | None = None
) -> Message:
    """Сообщение в группе: команда или служебное «группа стала супергруппой»."""
    return Message(
        message_id=1,
        date=SENT_AT,
        chat=group(chat_id),
        text=text_value,
        migrate_from_chat_id=migrate_from_chat_id,
    )


def sent(calls: list[TelegramMethod[Any]]) -> list[SendMessage]:
    return [call for call in calls if isinstance(call, SendMessage)]


async def test_chatid_in_a_group_answers_staff_only(harness: BotHarness) -> None:
    mod = await moderator(harness)
    stranger = telegram_user()
    await user_of(harness, stranger)

    [chatid] = sent(await harness.feed(mod, in_group("/chatid")))
    [start] = sent(await harness.feed(mod, in_group("/start@sosed_test_bot")))
    other_bot = await harness.feed(mod, in_group("/chatid@other_bot"))
    not_staff = await harness.feed(stranger, in_group("/chatid"))
    unknown = await harness.feed(telegram_user(), in_group("/start@sosed_test_bot"))

    assert chatid.chat_id == GROUP
    assert f"Id этого чата: <code>{GROUP}</code>" in chatid.text
    assert f"TELEGRAM_MODERATORS_CHAT_ID={GROUP}" in chatid.text
    assert start.text == chatid.text
    # чужому боту, не персоналу и незнакомцу в группе бот не отвечает
    assert sent(other_bot) == sent(not_staff) == sent(unknown) == []


async def test_configured_moderators_chat_is_recognised(harness: BotHarness) -> None:
    mod = await moderator(harness)

    [reply] = sent(await harness.feed(mod, in_group("/chatid", chat_id=CHAT)))

    assert reply.chat_id == CHAT
    assert reply.text == "Это чат модераторов, карточки кейсов приходят сюда."


async def test_bot_added_by_staff_tells_the_chat_id(harness: BotHarness) -> None:
    mod = await moderator(harness)
    stranger = telegram_user()
    await user_of(harness, stranger)

    [added] = sent(await harness.bot_added(mod, group()))
    by_stranger = await harness.bot_added(stranger, group(GROUP - 1))
    # настройки группы превратили её в супергруппу: id сменился — бот присылает новый
    [migrated] = sent(
        await harness.feed(mod, in_group(chat_id=GROUP - 2, migrate_from_chat_id=GROUP))
    )

    assert added.chat_id == GROUP
    assert f"TELEGRAM_MODERATORS_CHAT_ID={GROUP}" in added.text
    assert sent(by_stranger) == []
    assert migrated.chat_id == GROUP - 2
    assert f"TELEGRAM_MODERATORS_CHAT_ID={GROUP - 2}" in migrated.text
