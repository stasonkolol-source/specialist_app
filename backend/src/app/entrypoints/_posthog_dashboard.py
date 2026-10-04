"""`cli posthog-dashboard` (DEVELOPMENT_PLAN 6.6, K32): план или применение дашборда ликвидности.

Ключ — personal API key владельца (`ANALYTICS_POSTHOG_PERSONAL_API_KEY`) и id проекта
(`ANALYTICS_POSTHOG_PROJECT_ID`). Без них команда отказывает, а не идёт в PostHog наугад.
"""

from dataclasses import dataclass, field

import httpx

from app.platform.analytics.dashboard import liquidity_dashboard
from app.platform.analytics.posthog_dashboard import (
    DashboardSync,
    PostHogApiError,
    api_host,
    client_for,
)
from app.platform.settings import AnalyticsSettings

SCOPES = "dashboard:read, dashboard:write, insight:read, insight:write"


@dataclass
class DashboardOutcome:
    lines: list[str] = field(default_factory=list)
    failed: bool = False


async def run_posthog_dashboard(
    settings: AnalyticsSettings,
    *,
    environment: str,
    apply: bool,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DashboardOutcome:
    key, project = settings.posthog_personal_api_key, settings.posthog_project_id
    if key is None or project is None:
        missing = [
            name
            for name, value in (
                ("ANALYTICS_POSTHOG_PERSONAL_API_KEY", key),
                ("ANALYTICS_POSTHOG_PROJECT_ID", project),
            )
            if value is None
        ]
        return DashboardOutcome(
            [
                f"posthog-dashboard: не заданы {', '.join(missing)} в backend/.env — personal "
                f"API key PostHog со scope {SCOPES} и id проекта (K32, docs/OWNER_CHECKLIST.md)"
            ],
            failed=True,
        )
    host = api_host(settings.posthog_host)
    async with client_for(
        settings.posthog_host, project, key.get_secret_value(), transport=transport
    ) as client:
        try:
            result = await DashboardSync(client).sync(liquidity_dashboard(environment), apply=apply)
        except PostHogApiError as exc:
            return DashboardOutcome([f"posthog-dashboard: {exc}"], failed=True)
    mode = "применено" if apply else "план, без --apply ничего не меняется"
    lines = [f"PostHog {host}, проект {project}, события {environment} — {mode}:"]
    lines += [change.line() for change in result.pending]
    unchanged = len(result.changes) - len(result.pending)
    if unchanged:
        lines.append(f"  без изменений: {unchanged}")
    if apply and result.dashboard_id is not None:
        lines.append(f"Дашборд: {host}/project/{project}/dashboard/{result.dashboard_id}")
    return DashboardOutcome(lines)
