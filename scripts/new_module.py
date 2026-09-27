"""Генератор модуля и use case по шаблонам copier (ADR-0020 §12).

    make new-module NAME=<имя>                      — модуль с обязательными слоями
    make new-use-case MODULE=<модуль> NAME=<глагол_объект>

После копирования шаблона скрипт регистрирует модуль там, где код его ищет:
провайдер в entrypoints/_wiring.py, схема в platform/db/registry.py, контракт
«снаружи виден только api» в .importlinter. Место модуля в DAG (слой module-dag в
.importlinter) — архитектурное решение: скрипт о нём напоминает, но не выбирает.
Use case получает строку `provide(...)` в di.py своего модуля.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from copier import run_copy

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
MODULES = BACKEND / "src" / "app" / "modules"
WIRING = BACKEND / "src" / "app" / "entrypoints" / "_wiring.py"
REGISTRY = BACKEND / "src" / "app" / "platform" / "db" / "registry.py"
IMPORTLINTER = BACKEND / ".importlinter"

MODULE_NAME = re.compile(r"[a-z][a-z_]*[a-z]")
USE_CASE_NAME = re.compile(r"[a-z]+(_[a-z0-9]+)+")


def pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


def _insert_before(text: str, anchor: str, addition: str) -> str:
    index = text.index(anchor)
    return text[:index] + addition + text[index:]


def register_provider(name: str) -> None:
    text = WIRING.read_text(encoding="utf-8")
    provider = f"{pascal(name)}Provider"
    last_import = list(re.finditer(r"^from app\.modules\.\w+\.di import \w+\n", text, re.M))[-1]
    text = text[: last_import.end()] + f"from app.modules.{name}.di import {provider}\n" + text[last_import.end() :]
    block = re.search(r"MODULE_PROVIDERS: tuple\[type\[Provider\], \.\.\.\] = \(\n(.*?)\n\)", text, re.S)
    if block is None:
        raise SystemExit("MODULE_PROVIDERS not found in _wiring.py")
    text = text[: block.end(1)] + f"\n    {provider}," + text[block.end(1) :]
    WIRING.write_text(text, encoding="utf-8")


def register_schema(name: str) -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    block = re.search(r"MODULE_SCHEMAS: tuple\[str, \.\.\.\] = \(\n(.*?)\n\)", text, re.S)
    if block is None:
        raise SystemExit("MODULE_SCHEMAS not found in registry.py")
    text = text[: block.end(1)] + f'\n    "{name}",' + text[block.end(1) :]
    REGISTRY.write_text(text, encoding="utf-8")


def register_contract(name: str) -> None:
    layers = "\n".join(
        f"    app.modules.{name}.{layer}"
        for layer in ("domain", "application", "infrastructure", "errors", "di")
    )
    contract = (
        f"\n[importlinter:contract:only-api-{name}]\n"
        f"name = Снаружи модуля {name} виден только api (ADR-0002)\n"
        "type = protected\n"
        f"protected_modules =\n{layers}\n"
        f"allowed_importers =\n    app.modules.{name}\n    app.entrypoints\n"
    )
    IMPORTLINTER.write_text(IMPORTLINTER.read_text(encoding="utf-8") + contract, encoding="utf-8")


def register_use_case(module: str, name: str) -> None:
    di = MODULES / module / "di.py"
    text = di.read_text(encoding="utf-8")
    cls = pascal(name)
    line = f"from app.modules.{module}.application.use_cases.{name} import {cls}\n"
    text = _insert_before(text, "\n\n", "\n" + line.rstrip("\n")) if "import" in text else line + text
    if "provide" not in text.split("class", 1)[0]:
        text = text.replace("from dishka import Provider, Scope\n", "from dishka import Provider, Scope, provide\n")
    di.write_text(text.rstrip("\n") + f"\n    {name} = provide({cls})\n", encoding="utf-8")


def ruff_fix(*paths: Path) -> None:
    args = [str(p) for p in paths]
    subprocess.run(["ruff", "check", "--fix", "--quiet", *args], cwd=BACKEND, check=False)
    subprocess.run(["ruff", "format", "--quiet", *args], cwd=BACKEND, check=True)


def new_module(name: str) -> int:
    if not MODULE_NAME.fullmatch(name):
        print(f"bad module name {name!r}: snake_case, latin letters", file=sys.stderr)
        return 2
    if (MODULES / name).exists():
        print(f"module {name} already exists", file=sys.stderr)
        return 2
    run_copy(str(BACKEND / "templates" / "module"), str(MODULES), data={"name": name}, defaults=True, quiet=True)
    register_provider(name)
    register_schema(name)
    register_contract(name)
    ruff_fix(WIRING, REGISTRY, MODULES / name)
    print(f"created src/app/modules/{name}; registered provider, schema and only-api contract")
    print(f"next: place app.modules.{name} into the module-dag layers in backend/.importlinter")
    return 0


def new_use_case(module: str, name: str) -> int:
    if not (MODULES / module / "di.py").exists():
        print(f"module {module} not found", file=sys.stderr)
        return 2
    if not USE_CASE_NAME.fullmatch(name):
        print(f"bad use case name {name!r}: verb_object in snake_case", file=sys.stderr)
        return 2
    if (MODULES / module / "application" / "use_cases" / f"{name}.py").exists():
        print(f"use case {module}.{name} already exists", file=sys.stderr)
        return 2
    (MODULES / module / "application" / "use_cases").mkdir(exist_ok=True)
    init = MODULES / module / "application" / "use_cases" / "__init__.py"
    init.touch()
    run_copy(
        str(BACKEND / "templates" / "use_case"),
        str(BACKEND),
        data={"module": module, "name": name},
        defaults=True,
        quiet=True,
    )
    register_use_case(module, name)
    ruff_fix(
        MODULES / module / "di.py",
        MODULES / module / "application" / "use_cases" / f"{name}.py",
        MODULES / module / "tests" / "integration" / f"test_{name}.py",
    )
    print(f"created {module}/application/use_cases/{name}.py, test and di.py line")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    module = sub.add_parser("module")
    module.add_argument("name")
    use_case = sub.add_parser("use-case")
    use_case.add_argument("module")
    use_case.add_argument("name")
    args = parser.parse_args()
    if args.command == "module":
        return new_module(args.name)
    return new_use_case(args.module, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
