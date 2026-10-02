"""Служебные команды backend: `make cli ARGS='…'` из корня репозитория.

Команды добавляют шаги плана (dev-initdata, jwt-keys, seed, staff-grant …).
"""

import asyncio
import json
import secrets
import tomllib
from collections.abc import Awaitable, Callable
from enum import StrEnum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlencode

import typer

from app.entrypoints._envfile import read_env, write_env
from app.platform.i18n.catalogs import (
    COMPLETE,
    catalog_path,
    generate_sr_latn,
    read_catalog,
    stale_sr_latn,
)
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.localized import Locale
from app.platform.security.initdata import sign
from app.platform.security.jwt import JwtKeys, SigningKey
from app.platform.settings import (
    ENV_FILE,
    AiSettings,
    AppSettings,
    Environment,
    Settings,
    TelegramSettings,
)

if TYPE_CHECKING:  # модули грузятся лениво: CLI без БД не должен их импортировать
    from dishka import AsyncContainer

    from app.entrypoints._moderation_cli import CliOutcome
    from app.entrypoints._notify_test import NotifyTestOutcome
    from app.entrypoints._search_cli import ReindexReport
    from app.entrypoints._seed_demo import SeedReport
    from app.modules.identity.application.dto import OnboardingReset, StaffRoleGranted
    from app.modules.search.application.dto import ZeroResultStat
    from app.modules.specialists.application.use_cases.mark_founding import FoundingMarked

app = typer.Typer(help="«Соседи» — служебные команды backend.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Служебные команды backend «Соседей»."""


@app.command()
def version() -> None:
    """Показать версию backend."""
    try:
        typer.echo(package_version("sosed-backend"))
    except PackageNotFoundError:  # образ: код в /app/src без установки пакета
        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        typer.echo(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])


KEEP_JWT_KEYS = 2
"""Действующий ключ и предыдущий: токены, выпущенные до ротации, живут ещё 15 минут."""


@app.command("jwt-keys")
def jwt_keys(
    *,
    rotate: Annotated[
        bool, typer.Option("--rotate", help="Новый ключ подписи, старый — для проверки")
    ] = False,
    env_file: Annotated[Path, typer.Option(help="Файл .env")] = ENV_FILE,
) -> None:
    """Создать ключ подписи access JWT (Ed25519) в .env. Значения не выводятся."""
    current = read_env(env_file).get("JWT_KEYS", "")
    if current and not rotate:
        typer.echo(f"{env_file.name}: JWT_KEYS unchanged (use --rotate for a new signing key)")
        return
    keys = [SigningKey.generate().dump()]
    if current:
        JwtKeys.parse(current)  # испорченный JWT_KEYS не ротируем, а чиним руками
        keys += [item.strip() for item in current.split(",") if item.strip()][: KEEP_JWT_KEYS - 1]
    write_env(env_file, {"JWT_KEYS": ",".join(keys)})
    action = "rotated" if current else "added"
    typer.echo(f"{env_file.name}: JWT_KEYS {action} ({len(keys)} key(s), first signs)")


OPENAPI_FILE = ENV_FILE.parent / "openapi.json"


@app.command()
def openapi(
    *,
    check: Annotated[bool, typer.Option("--check", help="Только сверить файл с кодом")] = False,
    output: Annotated[Path, typer.Option(help="Файл схемы")] = OPENAPI_FILE,
) -> None:
    """Выгрузить контракт OpenAPI 3.1 в backend/openapi.json (DEVELOPMENT_PLAN 0.20)."""
    from app.entrypoints._wiring import module_routers
    from app.interfaces.http.app import openapi_spec

    text = json.dumps(openapi_spec(module_routers()), indent=2, ensure_ascii=False) + "\n"
    current = output.read_text(encoding="utf-8") if output.exists() else ""
    if check:
        if current != text:
            typer.echo(f"{output.name} is out of date: run `make openapi`", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"{output.name}: up to date")
        return
    output.write_text(text, encoding="utf-8")
    typer.echo(f"{output.name}: {'unchanged' if current == text else 'written'}")


i18n = typer.Typer(help="Каталоги gettext backend (ADR-0013).", no_args_is_help=True)
app.add_typer(i18n, name="i18n")


@i18n.command("generate")
def i18n_generate() -> None:
    """sr_Latn из sr_Cyrl транслитерацией."""
    source = catalog_path(Locale.SR_CYRL).read_text(encoding="utf-8")
    target = catalog_path(Locale.SR_LATN)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_sr_latn(source), encoding="utf-8")
    typer.echo(f"{target.relative_to(ENV_FILE.parent)}: generated")


@i18n.command("check")
def i18n_check() -> None:
    """sr_Latn актуален, ru и sr_Cyrl содержат одни и те же ключи."""
    problems = []
    if stale_sr_latn():
        problems.append("sr_Latn is stale: run `make cli ARGS='i18n generate'`")
    ru, sr = (set(read_catalog(catalog_path(locale))) for locale in COMPLETE)
    if ru != sr:
        problems.append(f"keys differ: only ru {sorted(ru - sr)}, only sr_Cyrl {sorted(sr - ru)}")
    for problem in problems:
        typer.echo(problem, err=True)
    if problems:
        raise typer.Exit(code=1)
    typer.echo(f"backend i18n: {len(ru)} keys, sr_Latn up to date")


@app.command("legal-validate")
def legal_validate() -> None:
    """Проверить тексты правовых документов backend/content/legal (DEVELOPMENT_PLAN 1.5a)."""
    from app.platform.legal.files import FileLegalLibrary, placeholders
    from app.platform.legal.port import LegalDocument
    from app.platform.settings import LegalSettings

    library = FileLegalLibrary(placeholders(AppSettings(), LegalSettings()))
    for document in LegalDocument:
        versions = sorted(library.versions(document))
        if not versions:
            typer.echo(f"error: {document.value}: no published versions", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"{document.value}: {', '.join(versions)}")
    typer.echo("legal: OK")


@app.command("seeds-validate")
def seeds_validate() -> None:
    """Проверить сиды пилотной зоны: гео, таксономию, запросы (DEVELOPMENT_PLAN 0.27)."""
    from app.entrypoints.seeds import validate

    report = validate()
    for line in report.summary:
        typer.echo(line)
    for warning in report.warnings:
        typer.echo(f"warning: {warning}")
    for error in report.errors:
        typer.echo(f"error: {error}", err=True)
    if not report.ok:
        raise typer.Exit(code=1)
    typer.echo("seeds: OK")


@app.command()
def seed() -> None:
    """Загрузить сиды в БД идемпотентно: гео (1.3a), каталог (1.3b), словарь модерации (2.4);
    повтор ничего не меняет."""
    from app.entrypoints.seeds import (
        load_catalog_seed,
        load_city_seeds,
        load_content_rules_seed,
        validate,
    )

    report = validate()
    if not report.ok:
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1)
    asyncio.run(_seed(load_city_seeds(), load_catalog_seed(), load_content_rules_seed()))


async def _seed(cities: list[Any], categories: list[Any], rules: list[Any]) -> None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.catalog.application.use_cases.import_catalog import (
        ImportCatalog,
        ImportCatalogCommand,
    )
    from app.modules.geo.application.use_cases.import_city import (
        ImportCity,
        ImportCityCommand,
    )
    from app.modules.moderation.application.use_cases.import_content_rules import (
        ImportContentRules,
        ImportContentRulesCommand,
    )

    container = make_worker_container(Settings())
    try:
        for city in cities:
            async with container() as request:
                use_case = await request.get(ImportCity)
                result = await use_case(ImportCityCommand(seed=city))
            typer.echo(
                f"geo {city.slug}: created {result.created}, updated {result.updated},"
                f" unchanged {result.unchanged}"
            )
        async with container() as request:
            import_catalog = await request.get(ImportCatalog)
            catalog = await import_catalog(ImportCatalogCommand(categories=tuple(categories)))
        typer.echo(
            f"catalog: created {catalog.created}, updated {catalog.updated},"
            f" unchanged {catalog.unchanged}"
        )
        async with container() as request:
            import_rules = await request.get(ImportContentRules)
            imported = await import_rules(ImportContentRulesCommand(rules=tuple(rules)))
        typer.echo(
            f"content rules: created {imported.created}, updated {imported.updated},"
            f" unchanged {imported.unchanged}, deactivated {imported.deactivated},"
            f" skipped {imported.skipped} (admin)"
        )
    finally:
        await container.close()


@app.command("set-menu-button")
def set_menu_button(
    url: Annotated[
        str | None, typer.Argument(help="Адрес Mini App; по умолчанию TELEGRAM_MINI_APP_URL")
    ] = None,
) -> None:
    """Кнопка меню бота открывает Mini App по адресу url (Bot API setChatMenuButton)."""
    asyncio.run(_set_menu_button(url))


@app.command("bot-setup")
def bot_setup(
    env: Annotated[
        Environment,
        typer.Option(help="Окружение бота; должно совпасть с APP_ENV — защита от чужого .env"),
    ],
) -> None:
    """Профиль бота: имя, описания и меню команд на ru и sr, кнопка меню (DEVELOPMENT_PLAN 1.6).

    Меняет только то, что отличается: повторный запуск ничего не трогает.
    """
    asyncio.run(_bot_setup(env))


async def _bot_setup(env: Environment) -> None:
    from aiogram import Bot
    from aiogram.exceptions import TelegramRetryAfter

    from app.interfaces.bot.profile import apply_menu_button, apply_profile, bot_profiles
    from app.platform.i18n.translator import Translator

    actual = AppSettings().env
    if actual is not env:
        typer.echo(f"bot-setup: --env {env.value}, but APP_ENV={actual.value}", err=True)
        raise typer.Exit(code=1)
    telegram = TelegramSettings()  # type: ignore[call-arg]  # из окружения и .env
    translator = Translator.load()
    profiles = bot_profiles(translator, env)
    problems = [problem for profile in profiles for problem in profile.problems()]
    if problems:
        typer.echo("bot-setup: " + "; ".join(problems), err=True)
        raise typer.Exit(code=1)
    bot = Bot(telegram.bot_token.get_secret_value())
    try:
        me = await bot.get_me()
        for profile in profiles:
            changed = await apply_profile(bot, profile)
            where = profile.language_code or "default"
            typer.echo(f"@{me.username} [{where}]: {', '.join(changed) or 'unchanged'}")
        url = telegram.mini_app_url
        if url and url.startswith("https://"):
            label = translator.text("bot.menu.open", Locale.RU) or "Open"
            state = "set" if await apply_menu_button(bot, url, label) else "unchanged"
            typer.echo(f"@{me.username}: menu button {state} → {url}")
        else:
            typer.echo(f"@{me.username}: menu button skipped (TELEGRAM_MINI_APP_URL is not https)")
    except TelegramRetryAfter as exc:
        typer.echo(
            f"bot-setup: Telegram asks to wait {exc.retry_after} s, run again later", err=True
        )
        raise typer.Exit(code=1) from exc
    finally:
        await bot.session.close()


async def _set_menu_button(url: str | None) -> None:
    from aiogram import Bot
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    from app.platform.i18n.translator import Translator

    telegram = TelegramSettings()  # type: ignore[call-arg]  # из окружения и .env
    target = url or telegram.mini_app_url
    if not target or not target.startswith("https://"):
        typer.echo("set-menu-button: need an https:// Mini App URL", err=True)
        raise typer.Exit(code=1)
    label = Translator.load().text("bot.menu.open", Locale.RU) or "Open"
    bot = Bot(telegram.bot_token.get_secret_value())
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=label, web_app=WebAppInfo(url=target))
        )
        me = await bot.get_me()
    finally:
        await bot.session.close()
    typer.echo(f"@{me.username}: menu button → {target}")


@app.command("dev-initdata")
def dev_initdata(
    *,
    user_id: Annotated[int, typer.Option(help="Telegram id пользователя")] = 100000001,
    first_name: Annotated[str, typer.Option()] = "Dev",
    username: Annotated[str | None, typer.Option()] = "sosed_dev_user",
    language: Annotated[str, typer.Option(help="language_code клиента")] = "ru",
    start_param: Annotated[str | None, typer.Option(help="startapp из deep link")] = None,
    url: Annotated[
        bool, typer.Option("--url", help="Адрес Mini App на стенде для браузера (mock-клиент)")
    ] = False,
) -> None:
    """initData, подписанный токеном dev-бота, — для curl и тестов без Telegram (только dev).

    `--url` печатает адрес Mini App на dev-стенде: mock-клиент Telegram с этим initData входит
    в backend по-настоящему (apps/tma/src/app/platform.ts) — экраны видны в обычном браузере.
    """
    settings = AppSettings()
    if settings.env is not Environment.DEV:
        typer.echo("dev-initdata works only with APP_ENV=dev", err=True)
        raise typer.Exit(code=1)
    user: dict[str, object] = {"id": user_id, "first_name": first_name, "language_code": language}
    if username:
        user["username"] = username
    fields = {
        "auth_date": str(int(SystemClock().now().timestamp())),
        "query_id": f"dev{secrets.token_hex(8)}",
        # Bot API 8.0: клиент Telegram передаёт подпись Ed25519; без поля SDK Mini App не
        # признаёт параметры запуска. backend её не проверяет, но она входит в hash
        "signature": "dev",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    if start_param:
        fields["start_param"] = start_param
    token = TelegramSettings().bot_token.get_secret_value()  # type: ignore[call-arg]  # из .env
    init_data = urlencode(fields | {"hash": sign(fields, token)})
    if url:
        query = urlencode({"platform": "mock", "lang": language, "initData": init_data})
        typer.echo(f"http://localhost:5173/?{query}")
    else:
        typer.echo(init_data)


@app.command("dev-reset-user")
def dev_reset_user(
    telegram_id: Annotated[int, typer.Argument(help="Telegram id пользователя dev-бота")],
) -> None:
    """Пройти онбординг S02a–c в Telegram заново: без города и намерения, согласия отозваны.

    Только dev (DEVELOPMENT_PLAN 1.5b): аккаунт, сессии и остальные данные остаются.
    """
    if AppSettings().env is not Environment.DEV:
        typer.echo("dev-reset-user works only with APP_ENV=dev", err=True)
        raise typer.Exit(code=1)
    result = asyncio.run(_dev_reset_user(telegram_id))
    if result is None:
        typer.echo("dev-reset-user: no such Telegram user (open the Mini App once)", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"user {result.user_id}: onboarding reset, {result.withdrawn_consents} consent(s)"
        " withdrawn; close and reopen the Mini App"
    )


async def _dev_reset_user(telegram_id: int) -> OnboardingReset | None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.identity.application.use_cases.reset_onboarding import (
        ResetOnboarding,
        ResetOnboardingCommand,
    )

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            reset = await request.get(ResetOnboarding)
            return await reset(ResetOnboardingCommand(telegram_id=telegram_id))
    finally:
        await container.close()


class StaffRole(StrEnum):
    """Роли персонала для `staff-grant` (platform/kernel/principal.py Role)."""

    MODERATOR = "moderator"
    SUPPORT = "support"
    ADMIN = "admin"


@app.command("staff-grant")
def staff_grant(
    tg_id: Annotated[int, typer.Option("--tg-id", help="Telegram id сотрудника")],
    role: Annotated[StaffRole, typer.Option("--role", help="Роль персонала")],
) -> None:
    """Выдать роль персонала (DEVELOPMENT_PLAN 2.5a): список — K29.

    Сотрудник должен хотя бы раз открыть бот или Mini App. Роль появится в токене при
    следующем входе; пароль, TOTP и вход в админку — шаг 2.7a. Выдача пишется в audit_log.
    """
    result = asyncio.run(_staff_grant(tg_id, role.value))
    if result is None:
        typer.echo("staff-grant: no such Telegram user (open the bot or Mini App once)", err=True)
        raise typer.Exit(code=1)
    state = "granted" if result.granted else "already granted"
    typer.echo(f"user {result.user_id}: role {result.role.value} {state}")


async def _staff_grant(telegram_id: int, role: str) -> StaffRoleGranted | None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.identity.application.use_cases.grant_staff_role import (
        GrantStaffRole,
        GrantStaffRoleCommand,
    )
    from app.platform.kernel.principal import Role

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            grant = await request.get(GrantStaffRole)
            return await grant(GrantStaffRoleCommand(telegram_id=telegram_id, role=Role(role)))
    finally:
        await container.close()


@app.command("founding-mark")
def founding_mark(
    tg_id: Annotated[int, typer.Option("--tg-id", help="Telegram id специалиста")],
) -> None:
    """Статус Founding профилю исполнителя (§15.2): первые 150–200 специалистов. Бейдж и
    бесплатный Pro — v1 (ADR-0014); в админке — 2.7b."""
    result = asyncio.run(_founding_mark(tg_id))
    if result is None:
        typer.echo("founding-mark: no such Telegram user or no specialist profile", err=True)
        raise typer.Exit(code=1)
    state = "marked" if result.marked else "already marked"
    typer.echo(f"profile {result.profile_id}: founding {state}")


async def _founding_mark(telegram_id: int) -> FoundingMarked | None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.specialists.application.use_cases.mark_founding import (
        MarkFounding,
        MarkFoundingCommand,
    )

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            mark = await request.get(MarkFounding)
            return await mark(MarkFoundingCommand(telegram_id=telegram_id))
    finally:
        await container.close()


class DemoScale(StrEnum):
    SMALL = "small"
    LAB = "lab"


@app.command("seed-demo")
def seed_demo(
    scale: Annotated[
        DemoScale,
        typer.Option(
            help=(
                "small — 60 специалистов с фото и 20 клиентов с заявками;"
                " lab — 50 000 специалистов без фото и 1 000 заявок"
            )
        ),
    ] = DemoScale.SMALL,
) -> None:
    """Демо-данные для dev и stage (2.8c, 5.1, 6.1a): специалисты — профили, прайс, районы и
    портфолио; клиенты — опубликованные заявки с откликами, часть — со сделкой. Всё через use
    cases, одобрено сразу. Повторный запуск количества не меняет. На проде не работает."""
    from app.entrypoints._seed_demo import SeedDemoRefusedError

    try:
        report = asyncio.run(_seed_demo(scale.value))
    except SeedDemoRefusedError as exc:
        typer.echo(f"seed-demo: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"seed-demo {scale.value}: {report.created} created, {report.skipped} already there,"
        f" {report.photos} photos, {report.jobs} jobs, {report.responses} responses,"
        f" {report.deals} deals ({report.completed} completed)"
    )


async def _seed_demo(scale: str) -> SeedReport:
    from app.entrypoints._seed_demo import SCALES, seed_demo

    return await seed_demo(Settings(), SCALES[scale], echo=typer.echo)


@app.command()
def reindex(
    *,
    everything: Annotated[
        bool, typer.Option("--all", help="Все опубликованные профили и все строки индекса")
    ] = False,
) -> None:
    """Пересобрать read-model поиска (4.1) в процессе CLI, без воркера: после смены формулы
    балла или состава строки, после восстановления базы. Отдельный профиль пересобирает
    воркер по событию."""
    if not everything:
        typer.echo("reindex: pass --all", err=True)
        raise typer.Exit(code=2)
    report = asyncio.run(_reindex())
    typer.echo(
        f"reindex: {report.published} published, {report.indexed_before} rows before;"
        f" {report.rebuilt} rebuilt, {report.removed} removed"
    )


@app.command("query-log-report")
def query_log_report(
    *,
    days: Annotated[int, typer.Option(min=1, max=90, help="За сколько дней")] = 7,
    limit: Annotated[int, typer.Option(min=1, max=500, help="Сколько запросов показать")] = 50,
) -> None:
    """Запросы без результатов (4.3b): что ищут и не находят — для еженедельного разбора
    словаря категорий. «filters» — сколько раз пустоту дали фильтры, а не пробел в словаре."""
    stats = asyncio.run(_query_log_report(days, limit))
    if not stats:
        typer.echo(f"query-log-report: no zero-result queries in {days} days")
        return
    typer.echo(f"query-log-report: top {len(stats)} zero-result queries in {days} days")
    for stat in stats:
        hint = f" -> {stat.did_you_mean}" if stat.did_you_mean else ""
        narrowed = f", filters {stat.narrowed}" if stat.narrowed else ""
        locales = ", ".join(stat.locales)
        typer.echo(f"{stat.count:>5}  {stat.q}  [{locales}]{hint}{narrowed}")


async def _query_log_report(days: int, limit: int) -> list[ZeroResultStat]:
    from app.entrypoints._search_cli import zero_results
    from app.entrypoints._wiring import make_worker_container

    container = make_worker_container(Settings())
    try:
        return await zero_results(container, days=days, limit=limit)
    finally:
        await container.close()


async def _reindex() -> ReindexReport:
    from app.entrypoints._search_cli import reindex_all
    from app.entrypoints._wiring import make_worker_container

    container = make_worker_container(Settings())
    try:
        return await reindex_all(container)
    finally:
        await container.close()


class Verdict(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class SeverityOption(StrEnum):
    """Тяжесть нарушения для лестницы санкций (moderation/domain/sanctions.py)."""

    MINOR = "minor"
    SERIOUS = "serious"
    CRITICAL = "critical"


@app.command("moderation-queue")
def moderation_queue(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Сколько кейсов")] = 30,
) -> None:
    """Открытые кейсы модерации по сроку (до чата модераторов 2.5b и админки 2.7b)."""
    outcome = asyncio.run(_moderation(lambda c: _queue(c, limit)))
    for line in outcome.lines:
        typer.echo(line)


@app.command("moderation-decide")
def moderation_decide(
    case: Annotated[str, typer.Argument(help="id кейса из moderation-queue")],
    verdict: Annotated[Verdict, typer.Argument(help="approve — нарушения нет, reject — есть")],
    by: Annotated[int, typer.Option("--by", help="Telegram id модератора (staff-grant)")],
    reason: Annotated[
        str | None, typer.Option("--reason", help="Код причины: contact_leak, spam_ad, …")
    ] = None,
    severity: Annotated[
        SeverityOption | None, typer.Option("--severity", help="Санкция по лестнице")
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="Заметка для журнала")] = None,
) -> None:
    """Решение по кейсу модерации: approve публикует объект, reject скрывает (DEVELOPMENT_PLAN
    2.6). При reject нужен --reason; --severity назначает ступень лестницы санкций."""
    outcome = asyncio.run(
        _moderation(
            lambda c: _decide(
                c,
                case_ref=case,
                approve=verdict is Verdict.APPROVE,
                by_telegram_id=by,
                reason=reason,
                severity=severity.value if severity else None,
                note=note,
            )
        )
    )
    for line in outcome.lines:
        typer.echo(line, err=not outcome.ok)
    if not outcome.ok:
        raise typer.Exit(code=1)


async def _moderation(
    run: Callable[[AsyncContainer], Awaitable[CliOutcome]],
) -> CliOutcome:
    from app.entrypoints._wiring import make_worker_container

    container = make_worker_container(Settings())
    try:
        return await run(container)
    finally:
        await container.close()


async def _queue(container: AsyncContainer, limit: int) -> CliOutcome:
    from app.entrypoints._moderation_cli import moderation_queue as run_queue

    return await run_queue(container, limit=limit)


async def _decide(container: AsyncContainer, **kwargs: Any) -> CliOutcome:
    from app.entrypoints._moderation_cli import moderation_decide as run_decide

    return await run_decide(container, **kwargs)


@app.command("notify-test")
def notify_test(
    user: Annotated[
        str, typer.Option("--user", help="Telegram id или внутренний id пользователя (UUID)")
    ],
) -> None:
    """Тестовое уведомление в бот: проверка канала и отправителя (DEVELOPMENT_PLAN 2.3b).

    Уведомление проходит весь конвейер — центр уведомлений, доставка, воркер, лимитер,
    Bot API; команда ждёт итога до 30 с. Человек должен был нажать /start в боте, а воркер —
    работать (`make dev`).
    """
    outcome = asyncio.run(_notify_test(user))
    typer.echo(outcome.message)
    if not outcome.sent:
        raise typer.Exit(code=1)


async def _notify_test(user_ref: str) -> NotifyTestOutcome:
    from app.entrypoints._notify_test import run_notify_test
    from app.entrypoints._wiring import make_worker_container

    container = make_worker_container(Settings())
    try:
        return await run_notify_test(container, user_ref)
    finally:
        await container.close()


@app.command("ai-smoke")
def ai_smoke(
    record: Annotated[
        Path | None,
        typer.Option(help="Сохранить сырые ответы провайдеров сюда (tests/unit/platform/recorded)"),
    ] = None,
) -> None:
    """Живой вызов OpenAI omni-moderation и Claude с ключами из настроек (DEVELOPMENT_PLAN 2.4).

    Проверяет ключи (K25, K26), модели и разбор ответа адаптерами; провайдер без ключа
    пропускается. Стоит доли цента. Код выхода 1 — ключей нет или проверка не состоялась.
    """
    from app.entrypoints._ai_smoke import run_ai_smoke

    if record is not None:
        record.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_ai_smoke(AiSettings(), record))
    for line in report.lines:
        typer.echo(line)
    for path in report.recorded:
        typer.echo(f"записано: {path}")
    if report.failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
