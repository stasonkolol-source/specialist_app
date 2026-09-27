"""Служебные команды backend: `make cli ARGS='…'` из корня репозитория.

Команды добавляют шаги плана (dev-initdata, jwt-keys, seed, staff-grant …).
"""

from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated

import typer

from app.entrypoints._envfile import read_env, write_env
from app.platform.security.jwt import JwtKeys, SigningKey
from app.platform.settings import ENV_FILE

app = typer.Typer(help="«Сосед» — служебные команды backend.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Служебные команды backend «Сосед»."""


@app.command()
def version() -> None:
    """Показать версию backend."""
    typer.echo(package_version("sosed-backend"))


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


if __name__ == "__main__":
    app()
