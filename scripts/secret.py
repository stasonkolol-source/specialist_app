"""make secret NAME=… TARGET=dev|tf-stage|tf-prod — скрытый ввод секрета владельцем.

В ответ печатается только имя и длина значения, само значение — никогда
(OWNER_CHECKLIST.md, «Как вписать секрет»). Цели stage и production добавляет шаг 0.25c.

Для тестов: --stdin читает значение из стандартного ввода, --file задаёт файл цели.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

from envfile import ROOT, update

TARGETS = {
    "dev": ROOT / "backend" / ".env",
    "tf-stage": ROOT / "infra" / "terraform" / "stage" / ".env",
    "tf-prod": ROOT / "infra" / "terraform" / "prod" / ".env",
}
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("target", choices=sorted(TARGETS))
    parser.add_argument("--stdin", action="store_true", help="прочитать значение из stdin")
    parser.add_argument("--file", type=Path, help="файл цели (для тестов)")
    args = parser.parse_args(argv)

    if not NAME_RE.match(args.name):
        sys.stderr.write("secret: NAME must look like GROUP_KEY (A-Z, 0-9, _)\n")
        return 2
    value = sys.stdin.readline().rstrip("\n") if args.stdin else getpass.getpass(f"{args.name}: ")
    value = value.strip()
    if not value:
        sys.stderr.write("secret: empty value, nothing written\n")
        return 1
    if any(ch in value for ch in "\"'\n "):
        sys.stderr.write("secret: quotes and spaces are not allowed (Docker --env-file)\n")
        return 1
    path = args.file or TARGETS[args.target]
    update(path, {args.name: value}, overwrite=True)
    sys.stdout.write(f"secret: {args.name} set ({len(value)} chars) in {args.target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
