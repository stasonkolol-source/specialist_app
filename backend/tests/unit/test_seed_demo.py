"""`cli seed-demo` (DEVELOPMENT_PLAN 2.8c): план демо-специалиста детерминирован и правдоподобен,
сербские тексты — латиницей, заглушка фото — JPEG, на проде команда отказывается работать.
Сам сид на базе — в интеграционном тесте."""

import io
import re
from datetime import UTC, datetime

import pytest
from PIL import Image
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._seed_demo import (
    DEMO_TELEGRAM_BASE,
    SCALES,
    SeedDemoRefusedError,
    placeholder_photo,
    plan,
    seed_demo,
)
from app.entrypoints._seed_demo_content import CATEGORIES, CLOSERS, OPENERS
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.contracts.events.identity import UserRegistered
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.settings import Settings

pytestmark = pytest.mark.unit

CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def test_same_number_is_the_same_specialist() -> None:
    assert plan(7) == plan(7)
    assert plan(7) != plan(8)
    assert plan(7).telegram_id == DEMO_TELEGRAM_BASE + 7


def test_demo_specialists_look_like_real_ones() -> None:
    demos = [plan(number) for number in range(SCALES["small"].specialists)]

    assert {demo.lang for demo in demos} == {"ru", "sr"}
    assert {demo.kind for demo in demos} == {ProfileKind.PRO, ProfileKind.CASUAL}
    assert len({demo.categories[0].slug for demo in demos}) >= 8
    for demo in demos:
        assert demo.lang in demo.languages
        assert set(demo.languages) <= {"ru", "sr", "en", "uk"}  # языки профиля (S34)
        assert len(demo.about) >= 80  # «о себе» засчитано в полноту
        assert 1 <= len(demo.district_picks) <= 4
        if demo.kind is ProfileKind.PRO:
            assert demo.services  # «Специалиста» без прайса на проверку не отправить
        else:
            assert not demo.photos
        assert ("at_client" in demo.work_modes) == (demo.travel_radius_km is not None)


def test_serbian_texts_are_latin() -> None:
    texts: list[str] = [*OPENERS["sr"], *CLOSERS["sr"]]
    for category in CATEGORIES:
        texts += [category.headline["sr"], category.skill["sr"], *category.captions["sr"]]
        for service in category.services:
            texts.append(service.title["sr"])
            if service.description:
                texts.append(service.description["sr"])
    assert [text for text in texts if CYRILLIC.search(text)] == []


def test_placeholder_photo_is_a_jpeg_of_its_own() -> None:
    first = placeholder_photo((214, 182, 96), 1)
    image = Image.open(io.BytesIO(first))

    assert (image.format, image.size) == ("JPEG", (1200, 900))
    assert placeholder_photo((214, 182, 96), 1) == first
    assert placeholder_photo((214, 182, 96), 2) != first


def test_registry_without_a_subscriber_keeps_the_others() -> None:
    first = TaskRef("test.first", UserRegistered)
    second = TaskRef("test.second", UserRegistered)
    tracked = TaskRef("analytics.capture", UserRegistered)
    registry = EventRegistry()
    for task in (first, second, tracked):
        registry.subscribe(UserRegistered, task)
    event = UserRegistered(
        user_id=UserId(new_id()), provider="telegram", occurred_at=datetime(2026, 10, 1, tzinfo=UTC)
    )

    assert registry.without("test.first", "analytics.").subscribers(event) == [second]
    assert registry.without("test.").subscribers(event) == [tracked]
    assert registry.subscribers(event) == [first, second, tracked]


def test_demo_telegram_ids_are_beyond_real_ones() -> None:
    # у настоящих пользователей Telegram ID — до 52 бит
    assert plan(0).telegram_id >= 2**52
    assert plan(SCALES["lab"].specialists).telegram_id < 2**53  # и без потерь в JS


async def test_production_refuses_demo_data(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "APP_ENV": "production",
        "APP_HASH_KEY": "test-hash-key",
        "LEGAL_OPERATOR_NAME": "Operator",
        "LEGAL_CONTACT_EMAIL": "support@example.test",
    }.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SeedDemoRefusedError):
        await seed_demo(Settings(env_file=None), SCALES["small"], echo=lambda _: None)


def test_cli_reports_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(*_: object, **__: object) -> None:
        raise SeedDemoRefusedError("seed-demo is for dev and stage only")

    monkeypatch.setattr("app.entrypoints._seed_demo.seed_demo", refuse)
    result = CliRunner().invoke(cli.app, ["seed-demo", "--scale", "lab"])

    assert result.exit_code == 1
    assert "dev and stage only" in result.output
