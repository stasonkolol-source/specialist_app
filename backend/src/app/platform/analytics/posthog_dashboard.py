"""`cli posthog-dashboard`: дашборд ликвидности в PostHog по спецификации dashboard.py (6.6, K32).

REST API PostHog с personal API key (scope `dashboard:read`, `dashboard:write`, `insight:read`,
`insight:write`). Адрес API — не адрес приёма событий: eu.i.posthog.com → eu.posthog.com.

Идемпотентно, по тегам, а не по названиям: дашборд — тег `sosed-liquidity-<окружение>`, плитка —
`<тег>:<ключ>`, текстовая плитка — по заголовку TEXT_MARKER (тегов у текста нет). Совпадает —
не трогаем, отличается — PATCH отличий, нет — создаём; плитка с тегом дашборда, которой нет в
спецификации, помечается удалённой (удаление в PostHog мягкое). Запрос сравнивается «включением»:
PostHog дописывает в сохранённый запрос свои поля по умолчанию, и полное равенство давало бы
правку на каждом запуске. Без `apply` — только чтение и план.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from app.platform.analytics.dashboard import TEXT_MARKER, DashboardSpec, InsightSpec

PAGE: Final = 100
_CLOUD_CAPTURE: Final = re.compile(r"^(?P<region>[a-z]+)\.i\.posthog\.com$")


def api_host(capture_host: str) -> str:
    """Адрес REST API по адресу приёма событий (`ANALYTICS_POSTHOG_HOST`): у облака они разные
    (eu.i.posthog.com → eu.posthog.com), у своего PostHog — один."""
    parts = urlsplit(capture_host)
    match = _CLOUD_CAPTURE.match(parts.hostname or "")
    if match is None:
        return capture_host.rstrip("/")
    return f"{parts.scheme}://{match['region']}.posthog.com"


class PostHogApiError(RuntimeError):
    """PostHog ответил ошибкой: ключ, scope, проект или запрос плитки."""


@dataclass(frozen=True, slots=True)
class Change:
    action: str
    """`создать`, `обновить`, `удалить` или `без изменений`."""
    target: str
    fields: tuple[str, ...] = ()

    def line(self) -> str:
        suffix = f" ({', '.join(self.fields)})" if self.fields else ""
        return f"  {self.action}: {self.target}{suffix}"


@dataclass
class SyncResult:
    changes: list[Change] = field(default_factory=list)
    dashboard_id: int | None = None

    @property
    def pending(self) -> list[Change]:
        return [c for c in self.changes if c.action != "без изменений"]


class DashboardSync:
    """Сверка дашборда со спецификацией. `client` — с base_url `…/api/projects/<id>/` и
    заголовком Authorization (cli: `client_for`)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def sync(self, spec: DashboardSpec, *, apply: bool) -> SyncResult:
        result = SyncResult()
        dashboard = await self._dashboard(spec, apply=apply, result=result)
        result.dashboard_id = dashboard_id = dashboard["id"] if dashboard else None
        found = await self._list("insights/", {"tags": json.dumps([spec.tag])})
        by_tag: dict[str, dict[str, Any]] = {}
        for stored in sorted(found, key=lambda item: item["id"]):
            if stored.get("deleted"):
                continue
            for tag in stored.get("tags") or ():
                by_tag.setdefault(tag, stored)  # копия с тем же тегом — старшая по id
        wanted = {spec.insight_tag(insight) for insight in spec.insights}
        for insight in spec.insights:
            existing = by_tag.get(spec.insight_tag(insight))
            await self._insight(spec, insight, existing, dashboard_id, apply=apply, result=result)
        for tag, stored in sorted(by_tag.items()):
            if tag.startswith(f"{spec.tag}:") and tag not in wanted:
                result.changes.append(Change("удалить", f"плитка «{stored.get('name')}»"))
                if apply:
                    await self._call("PATCH", f"insights/{stored['id']}/", {"deleted": True})
        await self._text(spec, dashboard_id, apply=apply, result=result)
        return result

    async def _dashboard(
        self, spec: DashboardSpec, *, apply: bool, result: SyncResult
    ) -> dict[str, Any] | None:
        candidates = [
            d
            for d in await self._list("dashboards/", {"search": spec.tag})
            if spec.tag in (d.get("tags") or ()) and not d.get("deleted")
        ]
        target = f"дашборд «{spec.name}»"
        wanted = {"name": spec.name, "description": spec.description}
        if not candidates:
            result.changes.append(Change("создать", target))
            if not apply:
                return None
            body = {**wanted, "tags": [spec.tag], "pinned": True}
            return await self._call("POST", "dashboards/", body)
        dashboard = min(candidates, key=lambda d: d["id"])
        diff = {k: v for k, v in wanted.items() if dashboard.get(k) != v}
        result.changes.append(Change("обновить" if diff else "без изменений", target, tuple(diff)))
        if diff and apply:
            await self._call("PATCH", f"dashboards/{dashboard['id']}/", diff)
        return dashboard

    async def _insight(
        self,
        spec: DashboardSpec,
        insight: InsightSpec,
        existing: Mapping[str, Any] | None,
        dashboard_id: int | None,
        *,
        apply: bool,
        result: SyncResult,
    ) -> None:
        target = f"плитка «{insight.name}»"
        wanted: dict[str, Any] = {
            "name": insight.name,
            "description": insight.description,
            "query": insight.query,
            "tags": [spec.tag, spec.insight_tag(insight)],
        }
        if existing is None:
            result.changes.append(Change("создать", target))
            if apply:
                await self._call("POST", "insights/", {**wanted, "dashboards": [dashboard_id]})
            return
        diff: dict[str, Any] = {}
        for key in ("name", "description"):
            if existing.get(key) != wanted[key]:
                diff[key] = wanted[key]
        if not _contains(existing.get("query"), insight.query):
            diff["query"] = insight.query
        if not set(wanted["tags"]) <= set(existing.get("tags") or ()):
            diff["tags"] = sorted({*wanted["tags"], *(existing.get("tags") or ())})
        tiles = [t for t in existing.get("dashboard_tiles") or () if not t.get("deleted")]
        if dashboard_id is not None and all(t.get("dashboard_id") != dashboard_id for t in tiles):
            # `dashboards` — устаревшее, но единственное поле записи плиток на дашборд
            diff["dashboards"] = sorted({*(t["dashboard_id"] for t in tiles), dashboard_id})
        result.changes.append(Change("обновить" if diff else "без изменений", target, tuple(diff)))
        if diff and apply:
            await self._call("PATCH", f"insights/{existing['id']}/", diff)

    async def _text(
        self, spec: DashboardSpec, dashboard_id: int | None, *, apply: bool, result: SyncResult
    ) -> None:
        target = "текстовая плитка «Метрики вне дашборда»"
        tile = None
        if dashboard_id is not None:
            dashboard = await self._call("GET", f"dashboards/{dashboard_id}/")
            tile = next(
                (
                    t
                    for t in dashboard.get("tiles") or ()
                    if TEXT_MARKER in ((t.get("text") or {}).get("body") or "")
                ),
                None,
            )
        if tile is None:
            result.changes.append(Change("создать", target))
            if apply and dashboard_id is not None:
                await self._call(
                    "POST", f"dashboards/{dashboard_id}/create_text_tile/", {"body": spec.text}
                )
            return
        same = tile["text"]["body"] == spec.text
        result.changes.append(Change("без изменений" if same else "обновить", target))
        if not same and apply:
            await self._call(
                "POST",
                f"dashboards/{dashboard_id}/update_text_tile/",
                {"tile_id": tile["id"], "body": spec.text},
            )

    async def _list(self, path: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
        page = await self._call("GET", path, params={**params, "limit": str(PAGE)})
        items = list(page.get("results") or ())
        while page.get("next"):
            page = await self._call("GET", page["next"])
            items += page.get("results") or ()
        return items

    async def _call(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            raise PostHogApiError(f"{method} {path}: {type(exc).__name__}") from exc
        if not response.is_success:
            raise PostHogApiError(
                f"{method} {path}: HTTP {response.status_code} {_detail(response)}"
            )
        data: dict[str, Any] = response.json()
        return data


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict) and payload.get("detail"):
        attr = f" [{payload['attr']}]" if payload.get("attr") else ""
        return f"{payload['detail']}{attr}"
    return str(payload)[:200]


def _contains(stored: Any, wanted: Any) -> bool:
    """`wanted` целиком есть в `stored`: словари — по своим ключам, списки — поэлементно."""
    if isinstance(wanted, dict):
        return isinstance(stored, dict) and all(
            _contains(stored.get(key), value) for key, value in wanted.items()
        )
    if isinstance(wanted, list):
        return (
            isinstance(stored, list)
            and len(stored) == len(wanted)
            and all(_contains(s, w) for s, w in zip(stored, wanted, strict=True))
        )
    return bool(stored == wanted)


def client_for(
    host: str,
    project_id: int,
    api_key: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{api_host(host)}/api/projects/{project_id}/",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
        transport=transport,
    )
