"""`cli seed-demo` на базе (DEVELOPMENT_PLAN 2.8c, 5.1): демо-специалисты и заявки демо-клиентов
созданы use cases и сразу опубликованы, повторный запуск количества не меняет, автопроверки в
очереди нет; фото работ — через хранилище (Garage) и обычную загрузку media, из кэша настоящих
фото — с аватаром, фото заявки и историей отзывов в прошлом. `--replace` удаляет прежних
демо-людей обычным удалением аккаунта и сеет новых, не трогая остальных."""

import io
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.entrypoints._seed_demo import (
    DEMO_CLIENT_BASE,
    DEMO_TELEGRAM_BASE,
    Scale,
    client_plan,
    plan,
    seed_demo,
)
from app.entrypoints._wiring import make_container
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.containers import GarageInfo
from tests.plugins.identity import new_telegram_id
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


async def scalar(settings: Settings, sql: str, **params: object) -> int:
    engine: AsyncEngine = create_async_engine(settings.db.dsn.get_secret_value())
    try:
        async with engine.connect() as conn:
            return int((await conn.execute(text(sql), params)).scalar_one())
    finally:
        await engine.dispose()


DEMO_PROFILES = (
    "FROM specialists.profiles p JOIN identity.auth_identities a ON a.user_id = p.user_id"
    " WHERE a.provider = 'telegram' AND CAST(a.subject AS bigint) BETWEEN :first AND :last"
)


def numbers(scale: Scale) -> dict[str, int]:
    return {
        "first": DEMO_TELEGRAM_BASE + scale.start,
        "last": DEMO_TELEGRAM_BASE + scale.start + scale.specialists - 1,
    }


DEMO_JOBS = (
    "FROM jobs.jobs j JOIN identity.auth_identities a ON a.user_id = j.client_id"
    " WHERE a.provider = 'telegram' AND CAST(a.subject AS bigint) BETWEEN :first AND :last"
)


async def test_seed_is_repeatable_and_published(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> None:
    settings = storage_settings  # заявке нужен media: фото нет, но порт собирается
    scale = Scale(4, photos=False, start=1000, clients=3)
    first = await seed_demo(settings, scale, echo=lambda _: None)
    again = await seed_demo(settings, scale, echo=lambda _: None)

    assert (first.created, first.skipped) == (4, 0)
    assert (again.created, again.skipped, again.jobs) == (0, 4, 0)
    planned = sum(len(client_plan(n).jobs) for n in range(scale.start, scale.start + 3))
    assert first.jobs == planned
    clients = {"first": DEMO_CLIENT_BASE + scale.start, "last": DEMO_CLIENT_BASE + scale.start + 2}
    published_jobs = await scalar(
        settings,
        f"SELECT count(*) {DEMO_JOBS} AND j.status = 'published' AND j.point_public IS NOT NULL",
        **clients,
    )
    assert published_jobs == planned - first.deals
    # отклики демо-специалистов (5.4): сразу прошедшие проверку, повтор сида их не плодит
    responses = await scalar(
        settings,
        "SELECT count(*) FROM jobs.responses r JOIN jobs.jobs j ON j.id = r.job_id"
        " JOIN identity.auth_identities a ON a.user_id = j.client_id WHERE a.provider ="
        " 'telegram' AND CAST(a.subject AS bigint) BETWEEN :first AND :last"
        " AND r.review = 'clear'",
        **clients,
    )
    assert responses == first.responses
    assert again.responses == 0
    # сделки (6.1a): заявка «в работе» (завершит её воркер по DealCompleted), повтор их не плодит
    assigned = await scalar(
        settings, f"SELECT count(*) {DEMO_JOBS} AND j.status = 'assigned'", **clients
    )
    deals = await scalar(
        settings,
        "SELECT count(*) FROM deals.deals d JOIN identity.auth_identities a"
        " ON a.user_id = d.client_id WHERE a.provider = 'telegram'"
        " AND CAST(a.subject AS bigint) BETWEEN :first AND :last AND d.status = 'completed'",
        **clients,
    )
    assert (assigned, deals) == (first.deals, first.completed)
    assert first.deals > 0
    assert (again.deals, again.completed) == (0, 0)
    # отзывы (7.2): по каждой выполненной сделке — опубликованный отзыв клиента
    reviews = await scalar(
        settings,
        "SELECT count(*) FROM reviews.reviews r JOIN identity.auth_identities a"
        " ON a.user_id = r.author_id WHERE a.provider = 'telegram'"
        " AND CAST(a.subject AS bigint) BETWEEN :first AND :last AND r.status = 'published'",
        **clients,
    )
    assert reviews == first.completed
    published = await scalar(
        settings, f"SELECT count(*) {DEMO_PROFILES} AND p.status = 'published'", **numbers(scale)
    )
    assert published == 4
    pros = sum(plan(n).services != () for n in range(scale.start, scale.start + 4))
    with_prices = await scalar(
        settings,
        f"SELECT count(DISTINCT p.id) {DEMO_PROFILES} AND EXISTS (SELECT 1 FROM pricing.services s"
        " WHERE s.profile_id = p.id AND s.deleted_at IS NULL)",
        **numbers(scale),
    )
    assert with_prices == pros
    checks = await scalar(
        settings,
        "SELECT count(*) FROM procrastinate_jobs j WHERE j.task_name = 'moderation.auto_check'"
        f" AND CAST(j.args->'payload'->>'entity_id' AS uuid) IN (SELECT p.id {DEMO_PROFILES})",
        **numbers(scale),
    )
    assert checks == 0
    # демо-люди не идут в аналитику, ленты уведомлений и атрибуцию
    side = await scalar(
        settings,
        "SELECT count(*) FROM procrastinate_jobs j WHERE (j.task_name LIKE 'analytics.%'"
        " OR j.task_name LIKE 'notifications.%' OR j.task_name LIKE 'growth.%')"
        " AND CAST(j.args->'payload'->>'user_id' AS uuid) IN"
        f" (SELECT p.user_id {DEMO_PROFILES})",
        **numbers(scale),
    )
    assert side == 0


@pytest.fixture
def storage_settings_with_garage(
    settings: Settings, garage: GarageInfo, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    monkeypatch.setenv("S3_ENDPOINT_URL", garage.endpoint_url)
    monkeypatch.setenv("S3_REGION", "garage")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", garage.access_key_id)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", garage.secret_access_key)
    return Settings(env_file=None)


async def test_portfolio_photos_go_through_storage(
    storage_settings_with_garage: Settings,
    geo_seeded: None,
    catalog_seeded: None,
    tmp_path: Path,
) -> None:
    start = next(n for n in range(2000, 3000) if len(plan(n).photos) >= 2)
    scale = Scale(1, photos=True, start=start)

    # кэша настоящих фото нет — заглушки
    report = await seed_demo(
        storage_settings_with_garage, scale, echo=lambda _: None, media_root=tmp_path
    )

    assert report.photos == len(plan(start).photos)
    works = await scalar(
        storage_settings_with_garage,
        "SELECT count(*) FROM specialists.portfolio_items i JOIN media.assets m ON m.id ="
        " (SELECT media_id FROM specialists.portfolio_media WHERE item_id = i.id LIMIT 1)"
        f" WHERE i.deleted_at IS NULL AND i.profile_id IN (SELECT p.id {DEMO_PROFILES})"
        " AND m.status = 'uploaded' AND i.status = 'published'",  # сид одобряет и работы (6.7)
        **numbers(scale),
    )
    assert works == report.photos


async def rows(settings: Settings, sql: str, **params: object) -> dict[UUID, str]:
    engine: AsyncEngine = create_async_engine(settings.db.dsn.get_secret_value())
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return {row[0]: row[1] for row in result}
    finally:
        await engine.dispose()


DEMO_USERS = (
    "SELECT u.id, u.display_name FROM identity.users u JOIN identity.auth_identities a"
    " ON a.user_id = u.id WHERE a.provider = 'telegram' AND u.status = 'active'"
    " AND CAST(a.subject AS bigint) IN (:s1, :s2, :c1, :c2)"
)


@pytest.fixture
async def real_user(storage_settings: Settings) -> AsyncIterator[UUID]:
    """Настоящий пользователь, чей запрос на удаление уже созрел: его исполнит воркер по
    расписанию, а не сид. База тестов общая — после теста запрос отменён, чтобы не достаться
    чужому ProcessDeletions."""
    user_id = new_id()
    engine: AsyncEngine = create_async_engine(storage_settings.db.dsn.get_secret_value())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO identity.users (id, display_name, version) VALUES (:id, 'Ana', 1)"
                ),
                {"id": user_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO identity.auth_identities (id, user_id, provider, subject)"
                    " VALUES (uuidv7(), :user, 'telegram', :subject)"
                ),
                {"user": user_id, "subject": str(new_telegram_id())},
            )
            await conn.execute(
                text(
                    "INSERT INTO identity.deletion_requests (id, user_id, source, requested_at,"
                    " execute_after) VALUES (uuidv7(), :user, 'tma', now() - interval '8 days',"
                    " now() - interval '1 day')"
                ),
                {"user": user_id},
            )
        yield user_id
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE identity.deletion_requests SET cancelled_at = now()"
                    " WHERE user_id = :user AND completed_at IS NULL"
                ),
                {"user": user_id},
            )
    finally:
        await engine.dispose()


async def test_replace_swaps_demo_people_and_keeps_real_users(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None, real_user: UUID
) -> None:
    settings = storage_settings
    scale = Scale(2, photos=False, start=3000, clients=2)
    ids = {
        "s1": DEMO_TELEGRAM_BASE + 3000,
        "s2": DEMO_TELEGRAM_BASE + 3001,
        "c1": DEMO_CLIENT_BASE + 3000,
        "c2": DEMO_CLIENT_BASE + 3001,
    }
    await seed_demo(settings, scale, echo=lambda _: None, language="sr")
    old = await rows(settings, DEMO_USERS, **ids)
    assert len(old) == 4

    report = await seed_demo(settings, scale, echo=lambda _: None, replace_existing=True)

    assert report.removed >= 4  # и демо-люди других тестов: база тестов общая
    assert (report.created, report.skipped) == (2, 0)
    new = await rows(settings, DEMO_USERS, **ids)
    assert len(new) == 4
    assert not new.keys() & old.keys()  # те же Telegram ID — новые аккаунты
    assert all(re.search("[А-яЁё]", name) for name in new.values())  # по умолчанию — по-русски
    gone = await rows(
        settings,
        "SELECT id, status FROM identity.users WHERE id = ANY(:ids)",
        ids=list(old),
    )
    assert set(gone.values()) == {"deleted"}
    kept = await rows(
        settings,
        "SELECT u.id, u.status || ':' || count(a.id) || ':' || count(r.id) FROM identity.users u"
        " LEFT JOIN identity.auth_identities a ON a.user_id = u.id"
        " LEFT JOIN identity.deletion_requests r ON r.user_id = u.id AND r.completed_at IS NULL"
        " WHERE u.id = :id GROUP BY u.id",
        id=real_user,
    )
    assert kept == {real_user: "active:1:1"}
    # повторная регистрация демо-ID — не сигнал риска: модерации нечего разбирать
    signals = await scalar(
        settings,
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'moderation.record_reregistration' AND args->'payload'->>'user_id' = ANY(:ids)",
        ids=[str(user_id) for user_id in new],
    )
    assert signals == 0
    # остальное удаляют подписчики UserDeleted, как у людей: профиль и заявки прежних
    container = make_container(settings)
    try:
        for user_id in old:
            await run_queued(container, "specialists.forget_profile", user_id=user_id)
            await run_queued(container, "jobs.forget_client", user_id=user_id)
    finally:
        await container.close()
    profiles = await scalar(
        settings,
        "SELECT count(*) FROM specialists.profiles WHERE user_id = ANY(:ids)"
        " AND deleted_at IS NULL",
        ids=list(old),
    )
    jobs = await scalar(
        settings,
        "SELECT count(*) FROM jobs.jobs WHERE client_id = ANY(:ids) AND status <> 'closed'",
        ids=list(old),
    )
    assert (profiles, jobs) == (0, 0)


def fake_cache(root: Path, category: str, problem: tuple[str, str] | None) -> Path:
    """Крошечный кэш, как после scripts/demo-media/fetch.py: два фото работ категории, фото
    «проблемы» (категория, предмет) к заявке и по аватару на пол."""
    rows: list[dict[str, object]] = []

    def jpeg(seed: int) -> bytes:
        image = Image.new("RGB", (800, 600), (200, 180, 150))
        draw = ImageDraw.Draw(image)
        for index in range(6):
            x, y = (seed * 97 + index * 211) % 800, (seed * 53 + index * 157) % 600
            draw.rectangle((x, y, x + 260, y + 150), fill=(30 * index, 90, 160 - seed))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=90)
        return out.getvalue()

    entries: list[tuple[str, str, dict[str, object]]] = [
        (
            f"{category}-p01",
            "portfolio",
            {"category": category, "caption": {"ru": "Работа", "sr": "Rad"}},
        ),
        (
            f"{category}-p02",
            "portfolio",
            {"category": category, "caption": {"ru": "Ещё", "sr": "Još"}},
        ),
    ]
    if problem is not None:
        entries.append(("problem-j01", "job", {"category": problem[0], "subject": problem[1]}))
    for index, (name, purpose, extra) in enumerate(entries, 1):
        path = root / purpose / f"{name}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg(index))
        rows.append(
            {"id": name, "purpose": purpose, "file": f"{purpose}/{name}.jpg", "mime": "image/jpeg"}
            | extra
        )
    for gender in ("f", "m"):
        path = root / "avatar" / f"avatar-{gender}-01.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (256, 256), (255, 213, 220)).save(path, format="PNG")
        rows.append(
            {
                "id": f"avatar-{gender}-01",
                "purpose": "avatar",
                "gender": gender,
                "file": f"avatar/avatar-{gender}-01.png",
                "mime": "image/png",
            }
        )
    (root / "index.json").write_text(json.dumps({"version": 1, "files": rows}))
    return root


async def test_real_photos_avatar_and_review_history(
    storage_settings_with_garage: Settings,
    geo_seeded: None,
    catalog_seeded: None,
    tmp_path: Path,
) -> None:
    settings = storage_settings_with_garage
    start = next(
        n
        for n in range(4000, 5000)
        if plan(n).avatar and plan(n).pre_platform and 3 <= plan(n).reviews <= 5
    )
    demo = plan(start)
    # фото «проблемы» — к заявке живого клиента, если у неё есть предмет на фото
    problem = next(
        ((job.category, job.photos) for job in client_plan(start).jobs if job.photos), None
    )
    root = fake_cache(tmp_path, demo.categories[0].slug, problem)
    scale = Scale(1, photos=True, start=start, clients=1, past_clients=3)

    report = await seed_demo(settings, scale, echo=lambda _: None, media_root=root)

    assert (report.created, report.avatars) == (1, 1)
    assert report.photos == 2  # оба фото кэша — у одного специалиста дубликатов нет
    assert report.past_deals == demo.reviews
    assert report.pre_platform == demo.pre_platform
    profile = {"first": DEMO_TELEGRAM_BASE + start, "last": DEMO_TELEGRAM_BASE + start}
    with_avatar = await scalar(
        settings, f"SELECT count(*) {DEMO_PROFILES} AND p.avatar_media_id IS NOT NULL", **profile
    )
    assert with_avatar == 1
    works = await scalar(
        settings,
        "SELECT count(*) FROM specialists.portfolio_items i WHERE i.deleted_at IS NULL"
        f" AND i.status = 'published' AND i.profile_id IN (SELECT p.id {DEMO_PROFILES})",
        **profile,
    )
    assert works == 2
    about = f"FROM reviews.reviews r WHERE r.subject_profile_id IN (SELECT p.id {DEMO_PROFILES})"
    deal_reviews = await scalar(
        settings,
        f"SELECT count(*) {about} AND r.kind = 'deal' AND r.status = 'published'",
        **profile,
    )
    assert deal_reviews == report.reviews >= demo.reviews
    # история — в прошлом: на карточке разные месяцы, а не «сегодня» у всех
    old = await scalar(
        settings,
        f"SELECT count(*) {about} AND r.kind = 'deal'"
        " AND r.published_at < now() - interval '2 days'",
        **profile,
    )
    assert old == demo.reviews
    replies = await scalar(
        settings, f"SELECT count(*) {about} AND r.reply_status = 'published'", **profile
    )
    assert replies == report.replies
    before_platform = await scalar(
        settings,
        f"SELECT count(*) {about} AND r.kind = 'pre_platform' AND r.status = 'published'",
        **profile,
    )
    assert before_platform == demo.pre_platform
    rated = await scalar(
        settings,
        "SELECT count(*) FROM reviews.rating_aggregates a WHERE a.rating_count >= :count"
        f" AND a.subject_profile_id IN (SELECT p.id {DEMO_PROFILES})",
        count=demo.reviews,
        **profile,
    )
    assert rated == 1
    clients = {"first": DEMO_CLIENT_BASE + start, "last": DEMO_CLIENT_BASE + start}
    job_photos = await scalar(
        settings,
        f"SELECT count(*) FROM jobs.job_media m WHERE m.job_id IN (SELECT j.id {DEMO_JOBS})",
        **clients,
    )
    assert job_photos == report.job_photos
