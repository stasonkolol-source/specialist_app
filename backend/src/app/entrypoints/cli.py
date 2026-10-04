"""Служебные команды backend: `make cli ARGS='…'` из корня репозитория.

Команды добавляют шаги плана (dev-initdata, jwt-keys, seed, staff-grant …).
"""

import asyncio
import json
import secrets
import tomllib
from collections.abc import Awaitable, Callable
from datetime import date
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
    AnalyticsSettings,
    AppSettings,
    Environment,
    Settings,
    SettingsError,
    TelegramSettings,
    UpdatesMode,
    webhook_base_url,
    webhook_problems,
)

if TYPE_CHECKING:  # модули грузятся лениво: CLI без БД не должен их импортировать
    from aiogram import Bot
    from dishka import AsyncContainer

    from app.entrypoints._moderation_cli import CliOutcome
    from app.entrypoints._notify_test import NotifyTestOutcome
    from app.entrypoints._search_cli import ReindexReport
    from app.entrypoints._seed_demo import SeedReport
    from app.modules.identity.application.dto import (
        OnboardingReset,
        StaffCredentialsSet,
        StaffRoleGranted,
        StaffTotpReencrypted,
    )
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
ADMIN_OPENAPI_FILE = ENV_FILE.parent / "admin-openapi.json"


@app.command()
def openapi(
    *,
    check: Annotated[bool, typer.Option("--check", help="Только сверить файлы с кодом")] = False,
    output: Annotated[Path, typer.Option(help="Файл схемы")] = OPENAPI_FILE,
    admin_output: Annotated[Path, typer.Option(help="Файл схемы Admin API")] = ADMIN_OPENAPI_FILE,
) -> None:
    """Выгрузить контракты OpenAPI 3.1: публичный API — backend/openapi.json (DEVELOPMENT_PLAN
    0.20), Admin API — backend/admin-openapi.json (2.7b: в публичную схему и api-client Mini App
    операции персонала не попадают)."""
    from app.entrypoints._wiring import module_admin_routers, module_routers
    from app.interfaces.http.admin_api import admin_openapi_spec
    from app.interfaces.http.app import openapi_spec

    stale = False
    for spec, target in (
        (openapi_spec(module_routers()), output),
        (admin_openapi_spec(module_admin_routers()), admin_output),
    ):
        text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if check:
            if current != text:
                typer.echo(f"{target.name} is out of date: run `make openapi`", err=True)
                stale = True
            else:
                typer.echo(f"{target.name}: up to date")
            continue
        target.write_text(text, encoding="utf-8")
        typer.echo(f"{target.name}: {'unchanged' if current == text else 'written'}")
    if stale:
        raise typer.Exit(code=1)


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
    """Профиль бота: имя, описания и меню команд на ru и sr, кнопка меню (DEVELOPMENT_PLAN 1.6),
    webhook по TELEGRAM_UPDATES (0.25e): webhook — setWebhook с секретом и узким
    allowed_updates, polling — снять webhook.

    Профиль и кнопку меняет только там, где они отличаются: повторный запуск их не трогает.
    """
    asyncio.run(_bot_setup(env))


async def _bot_setup(env: Environment) -> None:
    from aiogram import Bot
    from aiogram.exceptions import TelegramRetryAfter

    from app.interfaces.bot.profile import apply_menu_button, apply_profile, bot_profiles
    from app.platform.i18n.translator import Translator

    app_settings = AppSettings()
    actual = app_settings.env
    if actual is not env:
        typer.echo(f"bot-setup: --env {env.value}, but APP_ENV={actual.value}", err=True)
        raise typer.Exit(code=1)
    telegram = TelegramSettings()  # type: ignore[call-arg]  # из окружения и .env
    translator = Translator.load()
    profiles = bot_profiles(translator, env)
    problems = [problem for profile in profiles for problem in profile.problems()]
    # все проверки — до первого вызова Bot API: профиль без webhook хуже отказа целиком
    problems += webhook_problems(app_settings, telegram)
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
        typer.echo(f"@{me.username}: {await _apply_updates_mode(bot, app_settings, telegram)}")
    except TelegramRetryAfter as exc:
        typer.echo(
            f"bot-setup: Telegram asks to wait {exc.retry_after} s, run again later", err=True
        )
        raise typer.Exit(code=1) from exc
    finally:
        await bot.session.close()


async def _apply_updates_mode(
    bot: Bot, app_settings: AppSettings, telegram: TelegramSettings
) -> str:
    """Webhook по TELEGRAM_UPDATES; строка для вывода — адрес и типы апдейтов, без секрета."""
    from app.interfaces.bot.app import ALLOWED_UPDATES
    from app.interfaces.bot.webhook import apply_webhook, remove_webhook, webhook_url

    if telegram.updates is UpdatesMode.POLLING:
        return "webhook deleted (polling)" if await remove_webhook(bot) else "no webhook (polling)"
    secret = telegram.webhook_secret.get_secret_value() if telegram.webhook_secret else ""
    url = webhook_url(webhook_base_url(app_settings, telegram))
    await apply_webhook(bot, url, secret, ALLOWED_UPDATES)
    info = await bot.get_webhook_info()
    # ошибка доставки видна сразу: например, kamal-proxy не ведёт путь на процесс bot
    last_error = f", last error: {info.last_error_message}" if info.last_error_message else ""
    return (
        f"webhook set → {url} [{', '.join(ALLOWED_UPDATES)}],"
        f" pending {info.pending_update_count}{last_error}"
    )


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
    token = TelegramSettings().bot_token.get_secret_value()  # type: ignore[call-arg]  # из .env
    init_data = _signed_init_data(user, token, start_param=start_param)
    if url:
        query = urlencode({"platform": "mock", "lang": language, "initData": init_data})
        typer.echo(f"http://localhost:5173/?{query}")
    else:
        typer.echo(init_data)


def _signed_init_data(
    user: dict[str, object], token: str, *, start_param: str | None = None
) -> str:
    """initData, как его передаёт клиент Telegram, с подписью токеном бота."""
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
    return urlencode(fields | {"hash": sign(fields, token)})


LOADTEST_ENVS = (Environment.DEV, Environment.STAGE)


@app.command("loadtest-initdata")
def loadtest_initdata(
    *,
    count: Annotated[int, typer.Option(min=1, max=50_000, help="Сколько пользователей")] = 100,
    start: Annotated[int, typer.Option(min=0, help="Номер первого демо-специалиста")] = 0,
) -> None:
    """initData демо-специалистов `seed-demo` для нагрузочного прогона k6 (8.3): JSON-массив в
    stdout, подпись — токеном бота этого окружения, годен час (initdata.py). Только dev и stage.

    Синтетические пользователи — уже засеянные демо-специалисты (`seed-demo --scale lab`): у них
    приняты согласия и опубликован профиль, поэтому прогон откликается на заявки, ничего не
    создавая заново. Их Telegram ID длиннее 52 бит — живой человек под ними не войдёт.
    """
    if AppSettings().env not in LOADTEST_ENVS:
        typer.echo("loadtest-initdata works only with APP_ENV=dev or stage", err=True)
        raise typer.Exit(code=1)
    from app.entrypoints._seed_demo import plan

    token = TelegramSettings().bot_token.get_secret_value()  # type: ignore[call-arg]  # из окружения
    batch = []
    for number in range(start, start + count):
        demo = plan(number)
        user: dict[str, object] = {
            "id": demo.telegram_id,
            # те же имя и язык, что у сида: вход не переписывает демо-профиль
            "first_name": demo.first_name,
            "last_name": f"{demo.last_initial}.",
            "language_code": demo.lang,
        }
        batch.append(_signed_init_data(user, token))
    typer.echo(json.dumps(batch))


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


@app.command("staff-create")
def staff_create(
    tg_id: Annotated[int, typer.Option("--tg-id", help="Telegram id сотрудника")],
    login: Annotated[str, typer.Option("--login", help="Логин админки: a-z, 0-9, «.», «_», «-»")],
) -> None:
    """Вход в админку /admin (DEVELOPMENT_PLAN 2.7a): пароль и TOTP сотруднику с ролью.

    Сначала роль — `staff-grant`. Пароль (от 12 знаков) вводится здесь же дважды и не
    показывается; секрет TOTP печатается один раз — добавьте его в приложение-аутентификатор
    (Google Authenticator, 1Password, Aegis). Повторный вызов заменяет пароль и TOTP. В БД секрет
    ложится зашифрованным ключом APP_TOTP_KEY (8.4); на stage и проде без ключа — отказ.
    """
    import getpass

    password = getpass.getpass("Password (12+ chars): ")
    if password != getpass.getpass("Repeat password: "):
        typer.echo("staff-create: passwords do not match", err=True)
        raise typer.Exit(code=1)
    try:
        result = asyncio.run(_staff_create(tg_id, login, password))
    except _StaffCreateRefusedError as refused:
        typer.echo(f"staff-create: {refused}", err=True)
        raise typer.Exit(code=1) from None
    if result is None:
        typer.echo("staff-create: no such Telegram user (open the bot or Mini App once)", err=True)
        raise typer.Exit(code=1)
    state = "replaced" if result.replaced else "created"
    typer.echo(f"user {result.user_id}: admin login {result.login!r} {state}")
    typer.echo("TOTP secret (shown once, add it to your authenticator app now):")
    typer.echo(f"  {result.totp_secret}")
    typer.echo(f"  {result.totp_uri}")


class _StaffCreateRefusedError(Exception):
    pass


async def _staff_create(telegram_id: int, login: str, password: str) -> StaffCredentialsSet | None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.identity.application.use_cases.create_staff_login import (
        MIN_PASSWORD,
        CreateStaffLogin,
        CreateStaffLoginCommand,
    )
    from app.modules.identity.errors import (
        InvalidStaffLoginError,
        NotStaffError,
        StaffLoginTakenError,
    )

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            try:
                create = await request.get(CreateStaffLogin)
            except SettingsError as err:  # stage или прод без APP_TOTP_KEY (identity/di.py)
                raise _StaffCreateRefusedError(str(err)) from None
            try:
                return await create(
                    CreateStaffLoginCommand(telegram_id=telegram_id, login=login, password=password)
                )
            except InvalidStaffLoginError:
                raise _StaffCreateRefusedError(
                    f"login: 3-64 of a-z 0-9 . _ -; password: {MIN_PASSWORD}+ chars"
                ) from None
            except NotStaffError:
                raise _StaffCreateRefusedError("no staff role (run staff-grant first)") from None
            except StaffLoginTakenError:
                raise _StaffCreateRefusedError("login is taken by another staff member") from None
    finally:
        await container.close()


@app.command("staff-totp-reencrypt")
def staff_totp_reencrypt() -> None:
    """Перешифровать секреты TOTP персонала текущим APP_TOTP_KEY (8.4).

    После смены ключа (прежний — в APP_TOTP_KEY_PREVIOUS; infra/runbooks/secrets-rotation.md) и
    для строк до 8.4, где секрет лежит открытым. Повторный запуск ничего не меняет; секреты не
    печатаются. Код выхода 1 — есть секреты, которые не расшифровать: их сотрудникам — заново
    `staff-create`, а прежний ключ убирать только после этого.
    """
    try:
        result = asyncio.run(_staff_totp_reencrypt())
    except SettingsError as err:
        typer.echo(f"staff-totp-reencrypt: {err}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        f"staff TOTP secrets: {result.reencrypted} re-encrypted,"
        f" {result.current} already under the current key"
    )
    if result.undecryptable:
        users = ", ".join(str(user_id) for user_id in result.undecryptable)
        typer.echo(
            f"staff-totp-reencrypt: cannot decrypt for users {users}"
            " (wrong or missing APP_TOTP_KEY_PREVIOUS?); run staff-create for them",
            err=True,
        )
        raise typer.Exit(code=1)


async def _staff_totp_reencrypt() -> StaffTotpReencrypted:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.identity.application.use_cases.reencrypt_staff_totp_secrets import (
        ReencryptStaffTotpSecrets,
        ReencryptStaffTotpSecretsCommand,
    )

    container = make_worker_container(Settings())
    try:
        async with container() as request:
            reencrypt = await request.get(ReencryptStaffTotpSecrets)
            return await reencrypt(ReencryptStaffTotpSecretsCommand())
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


@app.command("export-user-data")
def export_user_data(
    user: Annotated[str, typer.Argument(help="id пользователя (UUID) или его Telegram id")],
    *,
    output: Annotated[Path | None, typer.Option(help="Файл JSON; по умолчанию — в stdout")] = None,
    note: Annotated[
        str | None, typer.Option(help="Основание: номер обращения в поддержку — в audit_log")
    ] = None,
) -> None:
    """Выгрузить данные пользователя по запросу (ZZPL, ответ — в 30 дней; DEVELOPMENT_PLAN 2.12b).

    JSON с разделами всех модулей и ссылками на файлы (живут сутки); выгрузка пишется в
    audit_log. Порядок работы поддержки — infra/runbooks/data-export.md.
    """
    from app.entrypoints._export_cli import export_user_data as run_export

    outcome = asyncio.run(run_export(user, note=note))
    if outcome is None:
        typer.echo(f"export-user-data: no such user: {user}", err=True)
        raise typer.Exit(code=1)
    text = json.dumps(outcome, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        typer.echo(text, nl=False)
        return
    output.write_text(text, encoding="utf-8")
    sections = ", ".join(outcome["sections"])
    typer.echo(f"{output}: user {outcome['user_id']}, sections: {sections}")


@app.command("beta-report")
def beta_report(
    week: Annotated[
        str,
        typer.Option(
            "--week",
            help="Неделя беты: 1 — первая, 0 — неделя до старта; all — сводка недель с первой "
            "по текущую (итоги беты, 7.7)",
        ),
    ],
    *,
    start: Annotated[
        str | None,
        typer.Option(help="Понедельник недели 1, ГГГГ-ММ-ДД; по умолчанию ANALYTICS_BETA_START"),
    ] = None,
) -> None:
    """Еженедельный отчёт беты (DEVELOPMENT_PLAN 6.6, 7.1): ликвидность по парам «город ×
    категория», стороны, доверие и SLA модерации — на текущий момент, под ролью readonly.
    `--week all` — таблица метрик ворот по всем неделям (7.7)."""
    try:
        beta_start = date.fromisoformat(start) if start else None
    except ValueError:
        typer.echo(f"beta-report: --start {start}: нужна дата ГГГГ-ММ-ДД", err=True)
        raise typer.Exit(code=2) from None
    if week != "all" and not week.isdigit():
        typer.echo(f"beta-report: --week {week}: нужен номер недели (0, 1, …) или all", err=True)
        raise typer.Exit(code=2)
    typer.echo(asyncio.run(_beta_report(None if week == "all" else int(week), beta_start)))


async def _beta_report(week: int | None, beta_start: date | None) -> str:
    from app.platform.analytics.beta_report import render, render_weeks
    from app.platform.analytics.liquidity import (
        beta_weeks,
        liquidity_report,
        reporting_connection,
        week_window,
    )

    settings = Settings()
    first = beta_start or settings.analytics.beta_start
    now = SystemClock().now()
    async with reporting_connection(settings.db) as conn:
        if week is not None:
            report = await liquidity_report(conn, week_window(first, week), as_of=now)
            return render(report, week=week)
        reports = await beta_weeks(conn, first, as_of=now)
    return render_weeks(reports, beta_start=first)


@app.command("posthog-dashboard")
def posthog_dashboard(
    *,
    apply: Annotated[
        bool, typer.Option("--apply", help="Создать или обновить дашборд; без флага — план")
    ] = False,
    environment: Annotated[
        Environment,
        typer.Option(help="Чьи события показывает дашборд (свойство environment)"),
    ] = Environment.PRODUCTION,
) -> None:
    """Дашборд ликвидности в PostHog как код (DEVELOPMENT_PLAN 6.6, K32).

    Без --apply — план: что будет создано, обновлено или удалено (только чтение). С --apply —
    дашборд и плитки по platform/analytics/dashboard.py; повтор копий не плодит. Нужны
    ANALYTICS_POSTHOG_PERSONAL_API_KEY и ANALYTICS_POSTHOG_PROJECT_ID (K32).
    """
    from app.entrypoints._posthog_dashboard import run_posthog_dashboard

    outcome = asyncio.run(
        run_posthog_dashboard(AnalyticsSettings(), environment=environment.value, apply=apply)
    )
    for line in outcome.lines:
        typer.echo(line, err=outcome.failed)
    if outcome.failed:
        raise typer.Exit(code=1)


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


@app.command("sentry-test")
def sentry_test() -> None:
    """Отправить в Sentry тестовую ошибку и показать id события (DEVELOPMENT_PLAN 3.3).

    На stage и проде — через `kamal app exec`: окружение и релиз те же, что у процессов.
    Без SENTRY_DSN ничего не отправляет: сообщение и код выхода 1.
    """
    from app.platform.observability.sentry import init_sentry, send_test_event

    settings = Settings()
    if not init_sentry(settings, process="cli"):
        typer.echo("SENTRY_DSN не задан: Sentry выключен, событие не отправлено.", err=True)
        raise typer.Exit(code=1)
    event_id = send_test_event()
    if event_id is None:  # before_send или sample_rate отбросили событие
        typer.echo("Sentry не принял событие: проверьте настройки SDK.", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"Тестовое событие отправлено в Sentry: {event_id}"
        f" (окружение {settings.app.env.value}, релиз {settings.app.release})"
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
    """Открытые кейсы модерации по сроку (решают и кнопками в чате модераторов, 2.5b)."""
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


class DisputeOutcome(StrEnum):
    """Исход сделки по спору (6.1c)."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"


@app.command("dispute-show")
def dispute_show(
    case: Annotated[str, typer.Argument(help="id кейса спора из moderation-queue (dispute/…)")],
    by: Annotated[int, typer.Option("--by", help="Telegram id модератора (staff-grant)")],
) -> None:
    """Спор по сделке (DEVELOPMENT_PLAN 6.1c): стороны, что случилось, ответ, сроки и ссылки на
    фото-доказательства на 5 минут. Просмотр пишется в журнал аудита."""
    outcome = asyncio.run(_moderation(lambda c: _dispute_show(c, case_ref=case, by_telegram_id=by)))
    for line in outcome.lines:
        typer.echo(line, err=not outcome.ok)
    if not outcome.ok:
        raise typer.Exit(code=1)


@app.command("dispute-resolve")
def dispute_resolve(
    case: Annotated[str, typer.Argument(help="id кейса спора из moderation-queue (dispute/…)")],
    outcome: Annotated[
        DisputeOutcome,
        typer.Argument(help="completed — работа выполнена, cancelled — сделка отменена"),
    ],
    by: Annotated[int, typer.Option("--by", help="Telegram id модератора (staff-grant)")],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Код причины: work_done, not_done, no_show, poor_quality, prepayment_scam,"
            " no_response, mutual, other",
        ),
    ],
    severity: Annotated[
        SeverityOption | None,
        typer.Option("--severity", help="Санкция второй стороне (о ком спор) по лестнице"),
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="Заметка для журнала")] = None,
) -> None:
    """Решение по спору (DEVELOPMENT_PLAN 6.1c): сделка завершена или отменена, сторонам —
    решение с причиной; --severity — санкция второй стороне."""
    result = asyncio.run(
        _moderation(
            lambda c: _dispute_resolve(
                c,
                case_ref=case,
                outcome=outcome.value,
                by_telegram_id=by,
                reason=reason,
                severity=severity.value if severity else None,
                note=note,
            )
        )
    )
    for line in result.lines:
        typer.echo(line, err=not result.ok)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("moderation-demo")
def moderation_demo(
    tg_id: Annotated[
        int, typer.Option("--tg-id", help="Telegram id пользователя, о ком кейс (ему — решение)")
    ],
) -> None:
    """Демо-кейс для проверки чата модераторов (DEVELOPMENT_PLAN 2.5b): кейс P1 об аккаунте;
    worker пришлёт карточку в чат TELEGRAM_MODERATORS_CHAT_ID, решение кнопкой дойдёт до
    пользователя уведомлением."""
    outcome = asyncio.run(_moderation(lambda c: _demo(c, telegram_id=tg_id)))
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


async def _dispute_show(container: AsyncContainer, **kwargs: Any) -> CliOutcome:
    from app.entrypoints._moderation_cli import dispute_show as run_show

    return await run_show(container, **kwargs)


async def _dispute_resolve(container: AsyncContainer, **kwargs: Any) -> CliOutcome:
    from app.entrypoints._moderation_cli import dispute_resolve as run_resolve

    return await run_resolve(container, **kwargs)


async def _demo(container: AsyncContainer, **kwargs: Any) -> CliOutcome:
    from app.entrypoints._moderation_cli import moderation_demo as run_demo

    return await run_demo(container, **kwargs)


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
