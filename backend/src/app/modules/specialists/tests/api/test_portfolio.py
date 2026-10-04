"""Портфолио и фото профиля через API (DEVELOPMENT_PLAN 2.11): работы из загруженных файлов,
подписи, порядок, лимиты, удаление вместе с файлом; фото профиля и замена прежнего."""

import pytest
from tests.plugins.http import HttpApp

from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

from .conftest import Cabinet, cabinet_for

pytestmark = pytest.mark.integration


async def test_works_are_added_captioned_reordered_and_removed(cabinet: Cabinet) -> None:
    assert (await cabinet.create()).status_code == 201
    empty = await cabinet.portfolio("GET")
    assert empty.json() == {"items": [], "limits": {"image": 60, "video": 6}}

    photos = [await cabinet.media(), await cabinet.media()]
    video = await cabinet.media(kind="video")
    added = [await cabinet.portfolio("POST", media_id=m) for m in [*photos, video]]
    assert [r.status_code for r in added] == [201, 201, 201]
    first = added[0].json()
    assert (first["kind"], first["position"], first["media"]["status"]) == ("image", 0, "ready")
    assert first["media"]["variants"][0]["name"] == "thumb"
    assert first["status"] == "pending"  # новая работа ждёт проверки подписи и фото (6.7)
    # тот же файл второй раз — та же работа, а не копия
    again = await cabinet.portfolio("POST", media_id=photos[0])
    assert again.json()["id"] == first["id"]

    captioned = await cabinet.portfolio("PATCH", f"/{first['id']}", caption="  Люстра,   Лиман ")
    assert captioned.json()["caption"] == "Люстра, Лиман"
    checks = await cabinet.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'moderation.auto_check'"
        " AND args->'payload'->>'entity_id' = :id",
        id=first["id"],
    )
    assert checks == 2  # новая работа и новая подпись — в конвейер модерации
    ids = [r.json()["id"] for r in added]
    reordered = await cabinet.portfolio("PUT", "/order", item_ids=list(reversed(ids)))
    assert [w["id"] for w in reordered.json()["items"]] == list(reversed(ids))

    removed = await cabinet.portfolio("DELETE", f"/{ids[1]}")
    assert removed.status_code == 204
    works = (await cabinet.portfolio("GET")).json()["items"]
    assert [(w["id"], w["position"]) for w in works] == [(ids[2], 0), (ids[0], 1)]
    # файл удаляет задача media, поставленная вместе с записью портфолио
    assert await cabinet.discard_queued() == 1
    deleted = await cabinet.scalar(
        "SELECT deleted_at IS NOT NULL FROM media.assets WHERE id = :id", id=photos[1]
    )
    assert deleted is True
    hints = (await cabinet.get()).json()["completeness"]["hints"]
    assert {"code": "portfolio", "count": 1} in hints


@pytest.mark.authz
async def test_authz_foreign_work_cannot_be_captioned_or_removed(
    cabinet: Cabinet, web: HttpApp, storage_settings: Settings
) -> None:
    """Чужой ресурс (8.4): работа чужого портфолио для другого исполнителя не существует."""
    assert (await cabinet.create()).status_code == 201
    work = (await cabinet.portfolio("POST", media_id=await cabinet.media())).json()["id"]
    stranger = await cabinet_for(web, storage_settings)
    assert (await stranger.create()).status_code == 201

    captioned = await stranger.portfolio("PATCH", f"/{work}", caption="Чужая подпись")
    removed = await stranger.portfolio("DELETE", f"/{work}")

    assert captioned.status_code == 404, captioned.text
    assert removed.status_code == 404, removed.text
    works = (await cabinet.portfolio("GET")).json()["items"]
    assert [(w["id"], w["caption"]) for w in works] == [(work, None)]


async def test_only_own_portfolio_files_fit_and_limits_hold(cabinet: Cabinet) -> None:
    assert (await cabinet.create()).status_code == 201

    stranger = await cabinet.media(owner=await cabinet.other_user())
    foreign = await cabinet.portfolio("POST", media_id=stranger)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "media_not_found")
    avatar = await cabinet.media(purpose="avatar")
    wrong = await cabinet.portfolio("POST", media_id=avatar)
    assert (wrong.status_code, wrong.json()["code"]) == (409, "media_state_conflict")

    for _ in range(6):
        assert (
            await cabinet.portfolio("POST", media_id=await cabinet.media(kind="video"))
        ).status_code == 201
    full = await cabinet.portfolio("POST", media_id=await cabinet.media(kind="video"))
    assert (full.status_code, full.json()["code"]) == (409, "portfolio_full")
    assert (full.json()["kind"], full.json()["limit"]) == ("video", 6)
    order = await cabinet.portfolio("PUT", "/order", item_ids=[str(new_id())])
    assert (order.status_code, order.json()["code"]) == (422, "invalid_portfolio")


async def test_profile_photo_is_set_replaced_and_removed(cabinet: Cabinet) -> None:
    assert (await cabinet.create()).status_code == 201
    first, second = await cabinet.media(purpose="avatar"), await cabinet.media(purpose="avatar")

    set_first = await cabinet.call("PUT", "/avatar", media_id=first)
    assert set_first.json()["avatar"]["id"] == first
    replaced = await cabinet.call("PUT", "/avatar", media_id=second)
    assert replaced.json()["avatar"]["id"] == second
    cleared = await cabinet.call("PUT", "/avatar", media_id=None)
    assert cleared.json()["avatar"] is None

    assert await cabinet.discard_queued() == 2
    gone = await cabinet.scalar(
        "SELECT count(*) FROM media.assets WHERE id IN (:a, :b) AND deleted_at IS NOT NULL",
        a=first,
        b=second,
    )
    assert gone == 2


async def test_files_that_failed_processing_do_not_count_toward_completeness(
    cabinet: Cabinet,
) -> None:
    assert (await cabinet.create()).status_code == 201
    works = [await cabinet.media() for _ in range(3)]
    for media_id in works:
        assert (await cabinet.portfolio("POST", media_id=media_id)).status_code == 201
    avatar = await cabinet.media(purpose="avatar")
    assert (await cabinet.call("PUT", "/avatar", media_id=avatar)).status_code == 200
    hints = [hint["code"] for hint in (await cabinet.get()).json()["completeness"]["hints"]]
    assert "portfolio" not in hints
    assert "avatar" not in hints

    # обработка отклонила фото профиля и одну работу (модерация изображений — 6.7)
    await cabinet.execute(
        "UPDATE media.assets SET status = 'rejected' WHERE id IN (:a, :w)", a=avatar, w=works[0]
    )
    hints = (await cabinet.get()).json()["completeness"]["hints"]
    assert {"code": "portfolio", "count": 1} in hints
    assert {"code": "avatar", "count": None} in hints
