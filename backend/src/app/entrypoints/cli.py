"""Служебные команды backend: `make cli ARGS='…'` из корня репозитория.

Команды добавляют шаги плана (dev-initdata, jwt-keys, seed, staff-grant …).
"""

import asyncio
import json
import secrets
import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated, Any
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
from app.platform.settings import ENV_FILE, AppSettings, Environment, Settings, TelegramSettings

app = typer.Typer(help="«Сосед» — служебные команды backend.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Служебные команды backend «Сосед»."""


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
    """Загрузить сиды в БД идемпотентно: города и районы (1.3a); повтор ничего не меняет."""
    from app.entrypoints.seeds import load_city_seeds, validate

    report = validate()
    if not report.ok:
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1)
    asyncio.run(_seed_geo(load_city_seeds()))


async def _seed_geo(cities: list[Any]) -> None:
    from app.entrypoints._wiring import make_worker_container
    from app.modules.geo.application.use_cases.import_city import (
        ImportCity,
        ImportCityCommand,
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
) -> None:
    """initData, подписанный токеном dev-бота, — для curl и тестов без Telegram (только dev)."""
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
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    if start_param:
        fields["start_param"] = start_param
    token = TelegramSettings().bot_token.get_secret_value()  # type: ignore[call-arg]  # из .env
    typer.echo(urlencode(fields | {"hash": sign(fields, token)}))


if __name__ == "__main__":
    app()
