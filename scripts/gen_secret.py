"""make gen-secret [NAME=… ENV=stage|production] — случайный секрет stage или prod в окне владельца.

Без NAME — только печатает значение (для трубы: `make -s gen-secret | gh secret set …`); в файлы
не пишет никогда. С NAME и ENV — по OWNER_CHECKLIST, правило 6: показывает значение один раз (и
кладёт в буфер обмена), ждёт Enter — копия в менеджере паролей (K10a), — передаёт в секреты GitHub
environment (Q1(б), stdin gh) и стирает экран с прокруткой и буфер. Ctrl+C до Enter — в GitHub
ничего не уходит.

Значение — 32 случайных байта в hex (64 символа): годится и в DSN (пароли ролей входят в
`postgresql+psycopg://app:<пароль>@…`), и в secret_token webhook ([A-Za-z0-9_-]), и как ключ
HMAC. Ключи JWT и SSH — не строка из байтов, для них свои команды (подсказка в ответе).

Для тестов: --gh — исполняемый файл вместо gh.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys

from secret import GITHUB_ENVIRONMENTS, NAME_RE, gh_secret_set

SECRET_BYTES = 32
NOT_RANDOM_STRINGS = {
    "JWT_KEYS": "ключи Ed25519 с kid — cli jwt-keys (infra/runbooks/stage-bootstrap.md, шаг 3)",
    "DEPLOY_SSH_KEY": "пара ключей — ssh-keygen (infra/runbooks/stage-bootstrap.md, шаг 1)",
}
CLEAR_SCREEN = "\033[2J\033[3J\033[H"
"""Экран, прокрутка (3J — Terminal и iTerm2) и курсор в начало: значение не остаётся на экране."""


def _clipboard(value: str) -> bool:
    """Положить в буфер обмена macOS; только в терминале — тесты и трубы буфер не трогают."""
    if not sys.stdout.isatty() or shutil.which("pbcopy") is None:
        return False
    subprocess.run(["pbcopy"], input=value, text=True, check=False)  # noqa: S607 — системная
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?")
    parser.add_argument("env", nargs="?", choices=GITHUB_ENVIRONMENTS)
    parser.add_argument("--gh", default="gh", help="исполняемый файл gh (для тестов)")
    args = parser.parse_args(argv)

    value = secrets.token_hex(SECRET_BYTES)
    if args.name is None:
        sys.stdout.write(value + "\n")
        return 0
    if args.env is None or not NAME_RE.match(args.name):
        sys.stderr.write("usage: make gen-secret NAME=APP_DB_PASSWORD ENV=stage|production\n")
        return 2
    if hint := NOT_RANDOM_STRINGS.get(args.name):
        sys.stderr.write(f"gen-secret: {args.name} — {hint}\n")
        return 2

    copied = _clipboard(value)
    try:
        sys.stdout.write(
            f"{args.name} для {args.env} (показывается один раз"
            f"{', уже в буфере обмена' if copied else ''}):\n\n  {value}\n\n"
            "Сохраните в менеджер паролей (K10a) и нажмите Enter; Ctrl+C — отмена, в GitHub"
            " ничего не уйдёт. "
        )
        sys.stdout.flush()
        input()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write(CLEAR_SCREEN)
        sys.stderr.write(f"gen-secret: {args.name} отменён, в GitHub ничего не записано\n")
        return 1
    finally:
        if copied:
            _clipboard(" ")  # буфер — не хранилище: копия теперь в менеджере паролей
    sys.stdout.write(CLEAR_SCREEN)
    if not gh_secret_set(args.name, args.env, value, args.gh):
        # новое значение не генерируем: копия уже в менеджере паролей, её и вписать
        sys.stderr.write(
            f"gen-secret: значение — только в менеджере паролей; когда gh заработает:"
            f" make secret NAME={args.name} TARGET={args.env}\n"
        )
        return 1
    sys.stdout.write(
        f"gen-secret: {args.name} set ({len(value)} chars) in GitHub environment {args.env}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
