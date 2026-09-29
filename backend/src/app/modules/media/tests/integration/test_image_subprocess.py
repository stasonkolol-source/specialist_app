"""Фото обрабатывает дочерний процесс (ARCHITECTURE §10.3). Отказ по вине файла доходит до
воркера причиной; сбой самого процесса (зависание, убийство, мусор, подлог в ответе) —
ProcessingCrashedError: задача повторится, файл не отклоняется сразу. Секреты воркера
процессу не достаются."""

import sys

import pytest

from app.modules.media.application.ports import ProcessingCrashedError, UnprocessableMediaError
from app.modules.media.domain.asset import FailureReason
from app.modules.media.infrastructure.imaging import SubprocessImageProcessor
from app.modules.media.tests.images import exif, photo

pytestmark = pytest.mark.integration


def answering(answer: str) -> tuple[str, ...]:
    """Процесс, который пишет в ответ заданную строку."""
    script = f"import pathlib, sys; pathlib.Path(sys.argv[1], 'answer.json').write_text({answer!r})"
    return (sys.executable, "-c", script)


async def test_photo_is_processed_in_a_child_process() -> None:
    result = await SubprocessImageProcessor().process(photo("JPEG", exif=exif()))

    assert [v.name for v in result.variants] == ["thumb", "md", "lg"]
    assert result.variants[0].body[:4] == b"RIFF"  # WebP
    assert (result.width, result.height) == (1600, 1200)


async def test_file_refusal_reaches_the_worker() -> None:
    with pytest.raises(UnprocessableMediaError) as caught:
        await SubprocessImageProcessor().process(b"%PDF-1.7\n")

    assert caught.value.reason is FailureReason.UNSUPPORTED


@pytest.mark.parametrize(
    "command",
    [
        (sys.executable, "-c", "import time; time.sleep(30)"),  # завис
        (sys.executable, "-c", "import os; os._exit(9)"),  # убит: OOM-kill, рестарт
        (sys.executable, "-c", "print('ответа нет')"),
        answering("not json"),
        answering('{"fault": "internal", "error": "bug"}'),  # наша ошибка в процессе
        # подлог: процесс мог быть скомпрометирован декодером
        answering(
            '{"ok": true, "width": 1, "height": 1, "placeholder": "", "sha256": "00",'
            ' "variants": [{"name": "../../etc/passwd", "width": 1, "height": 1}]}'
        ),
    ],
    ids=["timeout", "killed", "no-answer", "garbage", "internal", "path-traversal"],
)
async def test_broken_child_is_retried_not_blamed_on_the_file(command: tuple[str, ...]) -> None:
    processor = SubprocessImageProcessor(timeout=2.0, command=command)

    with pytest.raises(ProcessingCrashedError):
        await processor.process(photo("JPEG"))


async def test_child_does_not_see_worker_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    probe = (
        "import json, os, pathlib, sys; "
        "leaked = 'S3_SECRET_ACCESS_KEY' in os.environ; "
        "pathlib.Path(sys.argv[1], 'answer.json').write_text("
        "json.dumps({'fault': 'file', 'reason': 'unreadable' if leaked else 'unsupported'}))"
    )

    with pytest.raises(UnprocessableMediaError) as caught:
        await SubprocessImageProcessor(command=(sys.executable, "-c", probe)).process(b"x")

    assert caught.value.reason is FailureReason.UNSUPPORTED  # переменной в процессе нет
