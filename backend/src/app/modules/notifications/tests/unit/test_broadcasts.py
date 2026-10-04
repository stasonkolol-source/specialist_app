"""Рассылки из админки (DEVELOPMENT_PLAN 2.7b): аудитория, статусы, приоритет и текст.

Рассылка — только в группах согласия S43, на русском и сербском, с одной кнопкой; её задачи
отправки берутся из очереди после всех остальных, текст админки уходит простым текстом.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.notifications.application.dto import BroadcastContent
from app.modules.notifications.domain.broadcast import (
    Audience,
    Broadcast,
    BroadcastAction,
    BroadcastId,
    BroadcastStatus,
    Segment,
    Targeting,
)
from app.modules.notifications.domain.catalog import CATALOG, EventGroup, NotificationType, Priority
from app.modules.notifications.errors import BroadcastStateError
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.telegram.callbacks import CallbackAction, parse_callback
from app.platform.telegram.port import AppButton, CallbackButton

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
TEXT = {Locale.RU: "Привет, соседи!", Locale.SR_CYRL: "Здраво, суседи!"}
NOVI_SAD, BELGRADE = CityId(1), CityId(2)


def _broadcast(**overrides: object) -> Broadcast:
    fields: dict[str, object] = {
        "id": BroadcastId(new_id()),
        "text": LocalizedText(TEXT),
        "group": EventGroup.MARKETING,
        "created_by": UserId(new_id()),
        "created_at": NOW,
    }
    fields.update(overrides)
    return Broadcast(**fields)  # type: ignore[arg-type]


def _status(broadcast: Broadcast) -> BroadcastStatus:
    """Статус после перехода: mypy сужает атрибут по прошлому assert."""
    return broadcast.status


def _segment(
    *, specialist: bool = False, founding: bool = False, city: CityId | None = NOVI_SAD
) -> Segment:
    return Segment(is_specialist=specialist, is_founding=founding, city_id=city)


@pytest.mark.parametrize(
    ("audience", "expected"),
    [
        (Audience.ALL, [True, True, True]),
        (Audience.SPECIALISTS, [False, True, True]),
        (Audience.CLIENTS, [True, False, False]),
        (Audience.FOUNDING, [False, False, True]),
    ],
)
def test_audience_picks_its_segment(audience: Audience, expected: list[bool]) -> None:
    targeting = Targeting(audience=audience)
    people = [_segment(), _segment(specialist=True), _segment(specialist=True, founding=True)]

    assert [targeting.includes(person) for person in people] == expected


def test_city_narrows_any_audience() -> None:
    targeting = Targeting(audience=Audience.SPECIALISTS, city_id=BELGRADE)

    assert targeting.includes(_segment(specialist=True, city=BELGRADE))
    assert not targeting.includes(_segment(specialist=True, city=NOVI_SAD))
    assert not targeting.includes(_segment(specialist=True, city=None))  # город не указан


def test_broadcast_goes_only_to_consent_groups() -> None:
    """Служебная группа не выключается в S43 — рассылка в ней обошла бы согласие."""
    _broadcast(group=EventGroup.GOODS_LAUNCH)
    for group in (EventGroup.ACCOUNT, EventGroup.JOB_MATCHES, EventGroup.MESSAGES):
        with pytest.raises(DomainValidationError):
            _broadcast(group=group)


def test_broadcast_needs_russian_and_serbian_and_one_button() -> None:
    with pytest.raises(DomainValidationError):
        _broadcast(text=LocalizedText({Locale.RU: "Только по-русски"}))
    with pytest.raises(DomainValidationError):
        _broadcast(text=LocalizedText({Locale.SR_LATN: "Samo srpski"}))
    with pytest.raises(DomainValidationError):
        _broadcast(text=LocalizedText({**TEXT, Locale.RU: "я" * 3501}))
    with pytest.raises(DomainValidationError):
        _broadcast(link="m_profile", action=BroadcastAction.PRO_WAITLIST)


def test_state_machine_draft_scheduled_sending_done() -> None:
    broadcast = _broadcast()
    broadcast.start(NOW, NOW + timedelta(hours=2))
    assert _status(broadcast) is BroadcastStatus.SCHEDULED
    with pytest.raises(BroadcastStateError):
        broadcast.start(NOW)  # второй старт
    assert broadcast.begin()
    assert _status(broadcast) is BroadcastStatus.SENDING
    broadcast.advance(UserId(new_id()))
    assert broadcast.finish(NOW)
    assert _status(broadcast) is BroadcastStatus.DONE
    assert not broadcast.finish(NOW)
    with pytest.raises(BroadcastStateError):
        broadcast.cancel(NOW)  # завершённую не отменить


def test_start_in_the_past_is_now_and_cancel_stops_fan_out() -> None:
    broadcast = _broadcast()
    broadcast.start(NOW, NOW - timedelta(minutes=5))
    assert _status(broadcast) is BroadcastStatus.SENDING
    assert broadcast.starts_at == NOW
    broadcast.cancel(NOW)
    assert _status(broadcast) is BroadcastStatus.CANCELLED
    assert not broadcast.begin()  # задача разбора аудитории после отмены ничего не ставит
    with pytest.raises(BroadcastStateError):
        broadcast.advance(UserId(new_id()))


def test_broadcast_sends_go_after_everything_else() -> None:
    """Задачи-подписчики ставятся с приоритетом 0: рассылка ниже, иначе тысячи её задач
    задержали бы подписчика, который создаёт сообщение чата или отклик."""
    spec = CATALOG[NotificationType.BROADCAST]

    assert spec.priority is Priority.P4
    assert spec.priority.job_priority < 0 <= Priority.P3.job_priority
    assert all(
        other.priority.job_priority > spec.priority.job_priority
        for type_, other in CATALOG.items()
        if type_ is not NotificationType.BROADCAST
    )
    assert not spec.quiet_exempt  # тихие часы получателя рассылка ждёт


@pytest.fixture(scope="module")
def renderer() -> GettextNotificationRenderer:
    return GettextNotificationRenderer(Translator.load(), "https://app.test/")


def _content(**overrides: object) -> BroadcastContent:
    fields: dict[str, object] = {
        "id": new_id(),
        "status": "sending",
        "text": {"ru": "Скидки <b>сегодня</b> & завтра", "sr-Cyrl": "Попусти данас"},
        "link": None,
        "action": None,
    }
    fields.update(overrides)
    return BroadcastContent(**fields)  # type: ignore[arg-type]


def test_broadcast_text_is_plain_and_on_reader_language(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.broadcast(_content(), Locale.RU)
    assert text == "Скидки &lt;b&gt;сегодня&lt;/b&gt; &amp; завтра"
    assert buttons == ()
    latin, _ = renderer.broadcast(_content(), Locale.SR_LATN)
    assert latin == "Popusti danas"  # латиница — транслитом кириллицы (§7.4)


def test_broadcast_buttons(renderer: GettextNotificationRenderer) -> None:
    content = _content(action=BroadcastAction.PRO_WAITLIST.value)
    _, (waitlist,) = renderer.broadcast(content, Locale.SR_CYRL)
    assert isinstance(waitlist, CallbackButton)
    data = parse_callback(waitlist.data)
    assert data is not None
    assert (data.action, data.id) == (CallbackAction.PRO_WAITLIST, content.id)
    assert "notifications." not in waitlist.text

    _, (open_app,) = renderer.broadcast(_content(link="m_profile"), Locale.RU)
    assert isinstance(open_app, AppButton)
    assert open_app.url.endswith("startapp=m_profile")
