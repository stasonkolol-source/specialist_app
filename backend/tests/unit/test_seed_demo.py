"""`cli seed-demo` (DEVELOPMENT_PLAN 2.8c, 5.1): планы демо-специалиста и демо-клиента
детерминированы и правдоподобны, сербские тексты — латиницей, заглушка фото — JPEG, на проде
команда отказывается работать.
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
    SeedReport,
    client_plan,
    placeholder_photo,
    plan,
    seed_demo,
)
from app.entrypoints._seed_demo_content import CATEGORIES, CLOSERS, JOBS, OPENERS
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
    assert plan(SCALES["lab"].specialists).telegram_id < client_plan(0).telegram_id
    assert client_plan(SCALES["small"].clients).telegram_id < 2**53  # и без потерь в JS


def test_demo_clients_post_one_or_two_jobs_in_their_language() -> None:
    clients = [client_plan(number) for number in range(SCALES["small"].clients)]

    assert client_plan(3) == client_plan(3)
    assert {client.lang for client in clients} == {"ru", "sr"}
    assert sum(len(client.jobs) for client in clients) > len(clients)
    categories = {category.slug for category in CATEGORIES}
    for client in clients:
        assert 1 <= len(client.jobs) <= 2
        assert len(client.district_picks) == len(client.jobs)
        for job in client.jobs:
            assert job.category in categories
            assert 5 <= len(job.title[client.lang]) <= 120  # как у формы S20a
            assert len(job.dinars) == {"fixed": 1, "range": 2, "negotiable": 0}[job.budget_type]


def test_demo_jobs_in_serbian_are_latin() -> None:
    for job in JOBS:
        assert not CYRILLIC.search(job.title["sr"] + job.description["sr"]), job.title["ru"]


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


def test_cli_reports_the_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    scales: list[str] = []

    async def seeded(scale: str) -> SeedReport:
        scales.append(scale)
        return SeedReport(created=58, skipped=2, photos=80, jobs=27)

    monkeypatch.setattr(cli, "_seed_demo", seeded)
    result = CliRunner().invoke(cli.app, ["seed-demo"])

    assert (result.exit_code, scales) == (0, ["small"])
    assert "seed-demo small: 58 created, 2 already there, 80 photos, 27 jobs" in result.output


def test_cli_reports_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(scale: str) -> SeedReport:
        raise SeedDemoRefusedError("seed-demo is for dev and stage only")

    monkeypatch.setattr(cli, "_seed_demo", refuse)
    result = CliRunner().invoke(cli.app, ["seed-demo", "--scale", "lab"])

    assert result.exit_code == 1
    assert "dev and stage only" in result.output
