"""make secret NAME=… TARGET=… — скрытый ввод секрета владельцем.

В ответ печатается только имя и длина значения, само значение — никогда
(OWNER_CHECKLIST.md, «Как вписать секрет»). dev, tf-stage, tf-prod, tf-zone — в .env-файл;
stage и production (0.25c) — в секреты GitHub environment через `gh secret set --env` по решению
Q1(б): значение уходит в stdin gh, а не в `--body`, которое осталось бы в истории shell и в
списке процессов.

Для тестов: --stdin читает значение из стандартного ввода, --file задаёт файл цели, --gh —
исполняемый файл вместо gh.
"""

from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

from envfile import ROOT, update

TARGETS = {
    "dev": ROOT / "backend" / ".env",
    "tf-stage": ROOT / "infra" / "terraform" / "stage" / ".env",
    "tf-prod": ROOT / "infra" / "terraform" / "prod" / ".env",
    "tf-zone": ROOT / "infra" / "terraform" / "zone" / ".env",
}
GITHUB_ENVIRONMENTS = ("stage", "production")
"""Q1(б): секреты stage и prod — в GitHub environments (только main, прочитать обратно нельзя)."""
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def gh_secret_set(name: str, environment: str, value: str, gh: str = "gh") -> bool:
    """Записать секрет environment через gh; False — gh не смог (сообщение gh уже в stderr)."""
    try:
        subprocess.run(  # noqa: S603 — аргументы проверены, значение — только в stdin
            [gh, "secret", "set", name, "--env", environment],
            input=value,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        sys.stderr.write("secret: gh не найден — brew install gh, затем gh auth login (K3)\n")
        return False
    except subprocess.CalledProcessError:
        sys.stderr.write(
            f"secret: gh secret set не прошёл — gh auth status; есть ли environment {environment}"
            " (Settings → Environments, K19)?\n"
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("target", choices=sorted([*TARGETS, *GITHUB_ENVIRONMENTS]))
    parser.add_argument("--stdin", action="store_true", help="прочитать значение из stdin")
    parser.add_argument("--file", type=Path, help="файл цели (для тестов)")
    parser.add_argument("--gh", default="gh", help="исполняемый файл gh (для тестов)")
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
    if args.target in GITHUB_ENVIRONMENTS:
        if not gh_secret_set(args.name, args.target, value, args.gh):
            return 1
        where = f"GitHub environment {args.target}"
    else:
        update(args.file or TARGETS[args.target], {args.name: value}, overwrite=True)
        where = args.target
    sys.stdout.write(f"secret: {args.name} set ({len(value)} chars) in {where}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
