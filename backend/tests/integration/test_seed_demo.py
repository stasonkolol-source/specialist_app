"""`cli seed-demo` на базе (DEVELOPMENT_PLAN 2.8c, 5.1): демо-специалисты и заявки демо-клиентов
созданы use cases и сразу опубликованы, повторный запуск количества не меняет, автопроверки в
очереди нет; фото работ — через хранилище (Garage) и обычную загрузку media."""

import pytest
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
from app.platform.settings import Settings
from tests.plugins.containers import GarageInfo

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
    assert published_jobs == planned
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
    storage_settings_with_garage: Settings, geo_seeded: None, catalog_seeded: None
) -> None:
    start = next(n for n in range(2000, 3000) if len(plan(n).photos) >= 2)
    scale = Scale(1, photos=True, start=start)

    report = await seed_demo(storage_settings_with_garage, scale, echo=lambda _: None)

    assert report.photos == len(plan(start).photos)
    works = await scalar(
        storage_settings_with_garage,
        "SELECT count(*) FROM specialists.portfolio_items i JOIN media.assets m ON m.id ="
        " (SELECT media_id FROM specialists.portfolio_media WHERE item_id = i.id LIMIT 1)"
        f" WHERE i.deleted_at IS NULL AND i.profile_id IN (SELECT p.id {DEMO_PROFILES})"
        " AND m.status = 'uploaded'",
        **numbers(scale),
    )
    assert works == report.photos
