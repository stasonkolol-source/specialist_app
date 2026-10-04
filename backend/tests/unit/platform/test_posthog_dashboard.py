"""Дашборд ликвидности PostHog как код (DEVELOPMENT_PLAN 6.6, K32) без сети: фейковый PostHog
на httpx.MockTransport хранит дашборды и плитки, как REST API (`/api/projects/<id>/…`)."""

import copy
import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.entrypoints._posthog_dashboard import run_posthog_dashboard
from app.platform.analytics.beta_report import PENDING
from app.platform.analytics.dashboard import (
    SQL_ONLY,
    TEXT_MARKER,
    InsightSpec,
    liquidity_dashboard,
)
from app.platform.analytics.events import EVENTS, METRICS, EventName
from app.platform.analytics.posthog_dashboard import api_host
from app.platform.settings import AnalyticsSettings

pytestmark = pytest.mark.unit

PROJECT = 4242
PAGE_SIZE = 5
SPEC = liquidity_dashboard("production")


class FakePostHog:
    """Состояние проекта и журнал запросов. Сохранённый запрос плитки PostHog дополняет своими
    полями (`version`) — повторный --apply не должен считать это отличием."""

    def __init__(self) -> None:
        self.dashboards: dict[int, dict[str, Any]] = {}
        self.insights: dict[int, dict[str, Any]] = {}
        self.texts: dict[int, dict[str, Any]] = {}  # tile id → {dashboard, body}
        self.requests: list[httpx.Request] = []
        self.fail: tuple[str, str, int] | None = None
        self._ids = iter(range(100, 10_000))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def writes(self) -> list[str]:
        return [f"{r.method} {self._path(r)}" for r in self.requests if r.method != "GET"]

    def _path(self, request: httpx.Request) -> str:
        prefix = f"/api/projects/{PROJECT}/"
        assert request.url.path.startswith(prefix), request.url
        return request.url.path.removeprefix(prefix)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "eu.posthog.com"
        assert request.headers["Authorization"] == "Bearer phx_personal"
        path = self._path(request)
        if self.fail and (request.method, path) == self.fail[:2]:
            detail = {"type": "authentication_error", "detail": "API key missing scope"}
            return httpx.Response(self.fail[2], json={**detail, "attr": None})
        body = json.loads(request.content) if request.content else {}
        query = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        parts = path.strip("/").split("/")
        match request.method, parts:
            case "GET", ["dashboards"]:
                found = [d for d in self.dashboards.values() if query["search"] in d["tags"]]
                return self._page(found, request, query)
            case "POST", ["dashboards"]:
                return self._create(self.dashboards, {**body, "deleted": False})
            case "GET", ["dashboards", ident]:
                return httpx.Response(200, json=self._dashboard(int(ident)))
            case "PATCH", ["dashboards", ident]:
                self.dashboards[int(ident)].update(body)
                return httpx.Response(200, json=self.dashboards[int(ident)])
            case "POST", ["dashboards", ident, "create_text_tile"]:
                return self._create(self.texts, {"dashboard": int(ident), "body": body["body"]})
            case "POST", ["dashboards", _, "update_text_tile"]:
                self.texts[body["tile_id"]]["body"] = body["body"]
                return httpx.Response(200, json={"id": body["tile_id"]})
            case "GET", ["insights"]:
                tags = set(json.loads(query["tags"]))
                found = [i for i in self.insights.values() if tags & set(i["tags"])]
                return self._page(found, request, query)
            case "POST", ["insights"]:
                return self._create(self.insights, self._stored({**body, "deleted": False}))
            case "PATCH", ["insights", ident]:
                self.insights[int(ident)].update(self._stored(body))
                return httpx.Response(200, json=self.insights[int(ident)])
        return httpx.Response(404, json={"detail": "Not found."})

    def _stored(self, body: dict[str, Any]) -> dict[str, Any]:
        stored = copy.deepcopy(body)
        if "query" in stored:
            stored["query"]["source"]["version"] = 2
        if "dashboards" in stored:
            stored["dashboard_tiles"] = [
                {"id": next(self._ids), "dashboard_id": d, "deleted": None}
                for d in stored.pop("dashboards")
            ]
        return stored

    def _create(self, table: dict[int, dict[str, Any]], row: dict[str, Any]) -> httpx.Response:
        ident = next(self._ids)
        table[ident] = {**row, "id": ident}
        return httpx.Response(201, json=table[ident])

    def _page(
        self, rows: list[dict[str, Any]], request: httpx.Request, query: dict[str, str]
    ) -> httpx.Response:
        # страницы по 5 и абсолютная ссылка `next`, как у PostHog: клиент обходит все
        offset = int(query.get("offset", 0))
        more = offset + PAGE_SIZE < len(rows)
        url = request.url.copy_merge_params({"offset": str(offset + PAGE_SIZE)})
        return httpx.Response(
            200,
            json={
                "count": len(rows),
                "next": str(url) if more else None,
                "results": rows[offset : offset + PAGE_SIZE],
            },
        )

    def _dashboard(self, ident: int) -> dict[str, Any]:
        tiles = [
            {"id": tile["id"], "insight": insight, "text": None}
            for insight in self.insights.values()
            for tile in insight.get("dashboard_tiles", ())
            if tile["dashboard_id"] == ident and not insight["deleted"]
        ]
        tiles += [
            {"id": tile_id, "insight": None, "text": {"body": text["body"]}}
            for tile_id, text in self.texts.items()
            if text["dashboard"] == ident
        ]
        return {**self.dashboards[ident], "tiles": tiles}


def settings(
    *, key: str | None = "phx_personal", project: int | None = PROJECT
) -> AnalyticsSettings:
    return AnalyticsSettings(
        _env_file=None,  # type: ignore[call-arg]  # параметр pydantic-settings
        posthog_host="https://eu.i.posthog.com",
        posthog_personal_api_key=SecretStr(key) if key else None,
        posthog_project_id=project,
    )


async def run(fake: FakePostHog, *, apply: bool) -> list[str]:
    outcome = await run_posthog_dashboard(
        settings(), environment="production", apply=apply, transport=fake.transport()
    )
    assert not outcome.failed, outcome.lines
    return outcome.lines


def nodes(insight: InsightSpec) -> Iterator[dict[str, Any]]:
    yield from insight.query["source"]["series"]


def test_every_product_metric_is_on_dashboard_or_in_text_card() -> None:
    on_dashboard = {i.metric for i in SPEC.insights if i.metric}
    assert on_dashboard | SQL_ONLY.keys() | PENDING.keys() == {m.name for m in METRICS}
    assert not on_dashboard & SQL_ONLY.keys()
    assert len({i.key for i in SPEC.insights}) == len({i.name for i in SPEC.insights}) == 14
    assert len(SPEC.text) <= 4000  # предел текстовой плитки PostHog
    assert SPEC.text.startswith(TEXT_MARKER)
    assert all(name in SPEC.text for name in (*SQL_ONLY, *PENDING))
    # цель PRODUCT — в описании плитки (у контекстных — «порога нет»)
    assert all(
        "цель" in i.description.lower() or "порог" in i.description.lower() for i in SPEC.insights
    )


def test_queries_use_real_event_properties() -> None:
    """Фильтры, математика и разрез — только по свойствам из таксономии events.py."""
    for insight in SPEC.insights:
        source = insight.query["source"]
        assert source["properties"] == [
            {"type": "event", "key": "environment", "operator": "exact", "value": ["production"]}
        ]
        for node in nodes(insight):
            spec = EVENTS[EventName(node["event"])]
            assert spec.properties is not None, node["event"]
            keys = {f["key"] for f in node.get("properties", ()) if f["type"] == "event"}
            keys |= {node["math_property"]} if "math_property" in node else set()
            assert keys <= spec.properties.keys(), (insight.key, keys)
        breakdown = source.get("breakdownFilter")
        if breakdown:
            # воронка берёт разрез с первого шага, тренд — с каждой серии
            series = nodes(insight) if source["kind"] == "TrendsQuery" else [source["series"][0]]
            needed = (
                {"category", "city"}
                if breakdown["breakdown_type"] == "hogql"
                else {breakdown["breakdown"]}
            )
            for node in series:
                props = EVENTS[EventName(node["event"])].properties or {}
                assert needed <= props.keys(), (insight.key, node["event"])


def test_response_tiles_are_split_as_far_as_events_allow() -> None:
    """Отклик несёт город и категорию заявки: доли откликов, TTFR и supply/demand — по паре;
    у сделки города нет — win rate по категориям; weekly active — по городам (цель — на зону)."""
    split = {
        insight.key: source["breakdownFilter"]
        for insight in SPEC.insights
        if "breakdownFilter" in (source := insight.query["source"])
    }

    pair = {key for key, breakdown in split.items() if breakdown["breakdown_type"] == "hogql"}
    assert pair == {
        "jobs",
        "response_rate_1h",
        "response_rate_4h",
        "response_rate_24h",
        "ttfr",
        "fill_rate_7d",
        "supply_demand",
    }
    assert split["win_rate"] == {"breakdown_type": "event", "breakdown": "category"}
    assert split["weekly_active_specialists"] == {"breakdown_type": "event", "breakdown": "city"}


def test_api_host_is_not_the_capture_host() -> None:
    assert api_host("https://eu.i.posthog.com") == "https://eu.posthog.com"
    assert api_host("https://us.i.posthog.com/") == "https://us.posthog.com"
    assert api_host("https://posthog.example.rs/") == "https://posthog.example.rs"


async def test_dry_run_only_reads_and_plans() -> None:
    fake = FakePostHog()

    lines = await run(fake, apply=False)

    assert fake.writes == []
    assert lines[0] == (
        "PostHog https://eu.posthog.com, проект 4242, события production — план, без --apply "
        "ничего не меняется:"
    )
    assert "  создать: дашборд «Ликвидность «Соседи» — production»" in lines
    assert sum(line.startswith("  создать: плитка") for line in lines) == 14
    assert lines[-1] == "  создать: текстовая плитка «Метрики вне дашборда»"


async def test_apply_creates_once_and_second_apply_changes_nothing() -> None:
    fake = FakePostHog()

    lines = await run(fake, apply=True)

    [dashboard] = fake.dashboards.values()
    assert dashboard["tags"] == ["sosed-liquidity-production"]
    assert dashboard["pinned"] is True
    assert lines[-1] == f"Дашборд: https://eu.posthog.com/project/4242/dashboard/{dashboard['id']}"
    assert len(fake.insights) == 14
    for insight in fake.insights.values():
        assert insight["dashboard_tiles"][0]["dashboard_id"] == dashboard["id"]
        [key_tag] = set(insight["tags"]) - {"sosed-liquidity-production"}
        assert key_tag.startswith("sosed-liquidity-production:")
    [text] = fake.texts.values()
    assert text["body"] == SPEC.text

    fake.requests.clear()
    again = await run(fake, apply=True)

    assert fake.writes == []
    assert again[1:] == ["  без изменений: 16", lines[-1]]
    assert len(fake.insights) == 14


async def test_apply_updates_only_what_differs_and_removes_obsolete() -> None:
    fake = FakePostHog()
    await run(fake, apply=True)
    [dashboard_id] = fake.dashboards
    by_name = {i["name"]: i for i in fake.insights.values()}
    renamed = by_name["TTFR: город × категория"]
    renamed["name"] = "TTFR (старое имя)"
    renamed["query"]["source"]["interval"] = "day"
    detached = by_name["Review rate"]
    detached["dashboard_tiles"] = [{"id": 1, "dashboard_id": 7, "deleted": None}]
    fake.insights[9999] = {
        "id": 9999,
        "name": "Старая плитка",
        "deleted": False,
        "tags": ["sosed-liquidity-production", "sosed-liquidity-production:old"],
    }
    [text_id] = fake.texts
    fake.texts[text_id]["body"] = TEXT_MARKER + "\nстарый текст"
    fake.requests.clear()

    lines = await run(fake, apply=True)

    patches = {
        r.url.path.rsplit("/", 2)[-2]: json.loads(r.content)
        for r in fake.requests
        if r.method == "PATCH"
    }
    assert patches[str(renamed["id"])].keys() == {"name", "query"}
    assert renamed["name"] == "TTFR: город × категория"
    assert renamed["query"]["source"]["interval"] == "week"
    assert patches[str(detached["id"])] == {"dashboards": [7, dashboard_id]}
    assert patches["9999"] == {"deleted": True}
    assert fake.texts[text_id]["body"] == SPEC.text
    assert len(fake.insights) == 15  # копий нет: удалённая плитка помечена, а не стёрта
    assert "  удалить: плитка «Старая плитка»" in lines
    assert "  обновить: плитка «TTFR: город × категория» (name, query)" in lines


async def test_api_error_stops_with_status_and_detail() -> None:
    fake = FakePostHog()
    fake.fail = ("POST", "insights/", 403)

    outcome = await run_posthog_dashboard(
        settings(), environment="production", apply=True, transport=fake.transport()
    )

    assert outcome.failed
    assert outcome.lines == ["posthog-dashboard: POST insights/: HTTP 403 API key missing scope"]
    assert "phx_personal" not in "".join(outcome.lines)


@pytest.mark.parametrize(
    ("key", "project", "missing"),
    [
        (None, PROJECT, "ANALYTICS_POSTHOG_PERSONAL_API_KEY"),
        ("phx_personal", None, "ANALYTICS_POSTHOG_PROJECT_ID"),
    ],
)
async def test_refuses_without_personal_key_or_project(
    key: str | None, project: int | None, missing: str
) -> None:
    fake = FakePostHog()

    outcome = await run_posthog_dashboard(
        settings(key=key, project=project),
        environment="production",
        apply=False,
        transport=fake.transport(),
    )

    assert outcome.failed
    assert fake.requests == []
    assert f"не заданы {missing} в backend/.env" in outcome.lines[0]
    assert "dashboard:write" in outcome.lines[0]
