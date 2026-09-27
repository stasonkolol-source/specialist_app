"""Запись в backend/.env без вывода значений (DEVELOPMENT_PLAN §2 «Секреты»)."""

from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    """Заменить или дописать ключи, сохранив остальные строки и порядок."""
    for key, value in values.items():
        if any(ch in value for ch in "\"'\n"):
            raise ValueError(f"{key}: quotes and newlines are not allowed in .env values")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values and not line.lstrip().startswith("#"):
            out.append(f"{key}={values[key]}")
            written.add(key)
        else:
            out.append(line)
    out.extend(f"{key}={value}" for key, value in values.items() if key not in written)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
