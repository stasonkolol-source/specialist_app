"""make secrets-check: какие переменные заданы, а какие пусты — без значений.

Список имён берётся из *.env.example; значения сверяются с соответствующими .env.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from envfile import ROOT, read

PAIRS = (
    (ROOT / "backend" / ".env.example", ROOT / "backend" / ".env"),
    (ROOT / "infra" / "compose" / ".env.example", ROOT / "infra" / "compose" / ".env"),
    # токены Terraform: stage (0.25a–b), prod (3.1a, 3.1c) и общий стек зоны Cloudflare (3.1a) —
    # make secret … TARGET=tf-stage|tf-prod|tf-zone
    *(
        (
            ROOT / "infra" / "terraform" / stack / ".env.example",
            ROOT / "infra" / "terraform" / stack / ".env",
        )
        for stack in ("stage", "prod", "zone")
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", nargs=2, type=Path, metavar=("EXAMPLE", "ENV"),
                        help="сверить одну пару файлов (для тестов)")
    args = parser.parse_args(argv)
    pairs = [tuple(args.pair)] if args.pair else PAIRS
    for example, env in pairs:
        names = list(read(example))
        values = read(env)
        rel = env.relative_to(ROOT) if env.is_relative_to(ROOT) else env
        sys.stdout.write(f"{rel}\n")
        for name in names:
            state = "задан" if values.get(name) else "пуст"
            sys.stdout.write(f"  {name:32} {state}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
