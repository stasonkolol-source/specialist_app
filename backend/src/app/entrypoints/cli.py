"""Служебные команды backend: `make cli ARGS='…'` из корня репозитория.

Команды добавляют шаги плана (dev-initdata, jwt-keys, seed, staff-grant …).
"""

from importlib.metadata import version as package_version

import typer

app = typer.Typer(help="«Сосед» — служебные команды backend.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Служебные команды backend «Сосед»."""


@app.command()
def version() -> None:
    """Показать версию backend."""
    typer.echo(package_version("sosed-backend"))


if __name__ == "__main__":
    app()
