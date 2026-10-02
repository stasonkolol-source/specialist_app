"""Диалог и сообщение (DEVELOPMENT_PLAN 6.3a; ARCHITECTURE §11.5): кто участвует, кто может писать,
прочитанное по UUIDv7; текст — без краёв, до 4000 знаков, контакты скрыты до договорённости."""

from datetime import UTC, datetime

import pytest

from app.modules.messaging.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationStatus,
    ParticipantRole,
)
from app.modules.messaging.domain.message import MAX_BODY, check_client_id, compose
from app.modules.messaging.errors import (
    CannotStartConversationError,
    ConversationClosedError,
    ConversationNotFoundError,
    InvalidMessageError,
)
from app.platform.contracts.events.messaging import ConversationStarted
from app.platform.kernel.ids import UserId, new_id
from app.platform.text.contact_masking import MASK

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
CLIENT = UserId(new_id())
PERFORMER = UserId(new_id())
STRANGER = UserId(new_id())


def for_response(initiator: UserId = PERFORMER) -> Conversation:
    return Conversation.for_response(
        conversation_id=new_id(),
        client_id=CLIENT,
        performer_id=PERFORMER,
        initiator_id=initiator,
        job_id=new_id(),
        response_id=new_id(),
        now=NOW,
    )


def test_response_conversation_starts_open_with_both_sides_and_an_event() -> None:
    conversation = for_response(initiator=CLIENT)

    assert conversation.kind is ConversationKind.JOB_RESPONSE
    assert conversation.status is ConversationStatus.OPEN
    assert conversation.is_new
    assert conversation.participant(CLIENT).role is ParticipantRole.CLIENT
    assert conversation.counterpart(CLIENT).user_id == PERFORMER
    [event] = conversation.pull_events()
    assert isinstance(event, ConversationStarted)
    assert (event.kind, event.initiator_id, event.response_id) == (
        "job_response",
        CLIENT,
        conversation.response_id,
    )

    conversation.mark_persisted()
    assert not conversation.is_new


def test_direct_conversation_is_started_by_the_client() -> None:
    conversation = Conversation.direct(
        conversation_id=new_id(), client_id=CLIENT, performer_id=PERFORMER, now=NOW
    )

    assert conversation.kind is ConversationKind.DIRECT
    assert (conversation.job_id, conversation.response_id) == (None, None)
    [event] = conversation.pull_events()
    assert isinstance(event, ConversationStarted)
    assert event.initiator_id == CLIENT


@pytest.mark.parametrize(
    ("client", "performer", "initiator", "reason"),
    [
        (CLIENT, CLIENT, CLIENT, "self"),
        (CLIENT, PERFORMER, STRANGER, "not_a_party"),
    ],
)
def test_conversation_needs_two_parties_and_one_of_them_starts_it(
    client: UserId, performer: UserId, initiator: UserId, reason: str
) -> None:
    with pytest.raises(CannotStartConversationError) as raised:
        Conversation.for_response(
            conversation_id=new_id(),
            client_id=client,
            performer_id=performer,
            initiator_id=initiator,
            job_id=new_id(),
            response_id=new_id(),
            now=NOW,
        )
    assert raised.value.params["reason"] == reason


def test_stranger_sees_no_conversation() -> None:
    conversation = for_response()

    actions = (conversation.participant, conversation.counterpart, conversation.ensure_writable)
    for action in actions:
        with pytest.raises(ConversationNotFoundError):
            action(STRANGER)
    with pytest.raises(ConversationNotFoundError):
        conversation.read(STRANGER, new_id())


@pytest.mark.parametrize("status", [ConversationStatus.CLOSED, ConversationStatus.BLOCKED])
def test_closed_or_blocked_conversation_is_read_only(status: ConversationStatus) -> None:
    conversation = for_response()
    conversation.status = status

    with pytest.raises(ConversationClosedError) as raised:
        conversation.ensure_writable(CLIENT)
    assert raised.value.params["conversation_status"] == status.value
    assert conversation.read(CLIENT, new_id())  # читать можно


def test_posted_message_is_read_by_its_author_and_moves_the_conversation_up() -> None:
    conversation = for_response()
    message_id = new_id()

    conversation.message_posted(sender_id=CLIENT, message_id=message_id, now=NOW)

    assert conversation.client.last_read_message_id == message_id
    assert conversation.performer.last_read_message_id is None
    assert conversation.last_message_at == NOW


def test_read_only_moves_forward() -> None:
    conversation = for_response()
    first, second = new_id(), new_id()  # UUIDv7: second позже first

    assert conversation.read(PERFORMER, second)
    assert not conversation.read(PERFORMER, first)  # опоздавший запрос не откатывает
    assert not conversation.read(PERFORMER, second)  # повтор — без изменений
    assert conversation.performer.last_read_message_id == second


def test_text_is_trimmed_and_limited() -> None:
    assert compose("  Добрый день!  ", contacts_locked=True).body == "Добрый день!"
    assert compose("я" * MAX_BODY, contacts_locked=True).body == "я" * MAX_BODY
    for text in ("", "   \n ", "я" * (MAX_BODY + 1)):
        with pytest.raises(InvalidMessageError) as raised:
            compose(text, contacts_locked=True)
        assert raised.value.params == {"field": "body", "reason": "length"}


@pytest.mark.parametrize(
    "text",
    [
        "Звоните +381 64 123 4567",
        "пишите в t.me/majstor_pera",
        "мой ник @majstor_pera",
        "ноль шесть четыре один два три четыре пять шесть семь",
        "почта pera@example.rs",
    ],
)
def test_contacts_are_hidden_until_the_deal(text: str) -> None:
    locked = compose(text, contacts_locked=True)
    assert locked.masked
    assert MASK in locked.body
    assert locked.payload == {"masked": True}

    opened = compose(text, contacts_locked=False)
    assert (opened.body, opened.masked, opened.payload) == (text, False, {})


def test_prepayment_request_is_marked_without_hiding_the_text() -> None:
    composed = compose("Нужна предоплата 50% на карту", contacts_locked=True)

    assert composed.prepayment
    assert not composed.masked
    assert composed.payload == {"prepayment": True}
    assert not compose("Оплата после работы", contacts_locked=True).prepayment


def test_client_message_id_is_optional_and_short() -> None:
    assert check_client_id(None) is None
    assert check_client_id("  ") is None
    assert check_client_id(" abc ") == "abc"
    with pytest.raises(InvalidMessageError) as raised:
        check_client_id("x" * 65)
    assert raised.value.params == {"field": "client_msg_id", "reason": "too_long"}
