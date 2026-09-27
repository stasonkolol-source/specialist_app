"""Работа с .env-файлами без вывода значений (DEVELOPMENT_PLAN §2 «Секреты»).

Значения никогда не печатаются: наружу — только имена ключей.
Кавычки в значениях запрещены: Docker `--env-file` их не снимает.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: Path) -> dict[str, str]:
    """Прочитать .env в словарь (комментарии и пустые строки пропускаются)."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def update(path: Path, values: dict[str, str], *, overwrite: bool = False) -> list[str]:
    """Дописать ключи в .env, сохранив порядок. Возвращает имена изменённых ключей."""
    for key, value in values.items():
        if any(ch in value for ch in "\"'\n"):
            raise ValueError(f"{key}: quotes and newlines are not allowed in .env values")
    current = read(path)
    changed = [k for k, v in values.items() if k not in current or (overwrite and current[k] != v)]
    if not changed:
        return []
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values and key in changed:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out.extend(f"{k}={values[k]}" for k in changed if k not in seen)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return changed
