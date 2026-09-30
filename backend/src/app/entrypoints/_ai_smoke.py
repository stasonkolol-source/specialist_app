"""`cli ai-smoke`: живой вызов AI-провайдеров с ключами из настроек (DEVELOPMENT_PLAN 2.4).

Ключи K25 (OpenAI) и K26 (Anthropic) — в backend/.env. Команда проверяет, что ключ принят,
модель доступна и ответ разбирается адаптером: два запроса к omni-moderation (бесплатно) и
три к классификатору (доли цента). Провайдер без ключа пропускается.

С `--record DIR` сырые ответы сохраняются в DIR под именами записанных ответов контрактных
тестов (tests/unit/platform/recorded): так записи, собранные по документации, заменяются
настоящими. Тексты проверок — синтетика, без персональных данных.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import httpx
import httpx2

from app.platform.ai.anthropic_classifier import AnthropicPolicyClassifier
from app.platform.ai.breaker import CircuitBreaker
from app.platform.ai.openai_moderation import OpenAiModeration
from app.platform.ai.port import ContentKind, PolicyLabel, Unavailable
from app.platform.settings import AiSettings

MODERATION_SAMPLES = (
    ("clean", "Treba mi električar da zameni tri utičnice u stanu, ove subote posle podne.", None),
    ("threat", "Ubiću te i tvoju porodicu ako ne vratiš novac do sutra.", "flagged"),
)
"""Имя, текст и имя записи (None — не записывать)."""
CLASSIFIER_SAMPLES = (
    (
        ContentKind.JOB,
        "Treba mi električar da zameni tri utičnice u stanu, ove subote posle podne.",
        PolicyLabel.OK,
        None,
    ),
    (
        ContentKind.RESPONSE,
        "Mogu da dođem sutra, ali prvo uplatite 50 evra unapred na moju karticu, inače ne dolazim.",
        PolicyLabel.PREPAYMENT_SCAM,
        "anthropic_prepayment.json",
    ),
    (
        ContentKind.JOB,
        "Zapošljavamo radnike za magacin, puno radno vreme, plata od 900 evra mesečno.",
        PolicyLabel.VACANCY,
        None,
    ),
)


@dataclass
class SmokeReport:
    lines: list[str] = field(default_factory=list)
    failed: bool = False
    recorded: list[Path] = field(default_factory=list)


class _Recorder:
    """Хук ответа HTTP-клиента: помнит тело последнего ответа провайдера."""

    def __init__(self) -> None:
        self.body: Any = None

    async def __call__(self, response: httpx.Response | httpx2.Response) -> None:
        await response.aread()
        try:
            self.body = response.json()
        except ValueError:  # не JSON (страница прокси) — адаптер сам скажет «недоступно»
            self.body = None

    def save(self, directory: Path | None, name: str, report: SmokeReport) -> None:
        if directory is None or self.body is None:
            return
        path = directory / name
        path.write_text(
            json.dumps(self.body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report.recorded.append(path)


async def run_ai_smoke(
    settings: AiSettings,
    record: Path | None = None,
    *,
    openai_transport: httpx.AsyncBaseTransport | None = None,
    anthropic_transport: httpx2.AsyncBaseTransport | None = None,
) -> SmokeReport:
    """Транспорты — для теста команды без сети; по умолчанию — настоящие."""
    report = SmokeReport()
    if settings.openai_api_key is None and settings.anthropic_api_key is None:
        report.lines.append(
            "нет ключей AI_OPENAI_API_KEY и AI_ANTHROPIC_API_KEY — нечего проверять"
        )
        report.failed = True
        return report
    if settings.openai_api_key is not None:
        key = settings.openai_api_key.get_secret_value()
        await _moderation(settings, key, record, report, openai_transport)
    else:
        report.lines.append("moderation: пропущено — нет AI_OPENAI_API_KEY (K25)")
    if settings.anthropic_api_key is not None:
        key = settings.anthropic_api_key.get_secret_value()
        await _classifier(settings, key, record, report, anthropic_transport)
    else:
        report.lines.append("classifier: пропущено — нет AI_ANTHROPIC_API_KEY (K26)")
    return report


async def _moderation(
    settings: AiSettings,
    key: str,
    record: Path | None,
    report: SmokeReport,
    transport: httpx.AsyncBaseTransport | None,
) -> None:
    recorder = _Recorder()
    timeout = httpx.Timeout(settings.timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(
        timeout=timeout, transport=transport, event_hooks={"response": [recorder]}
    ) as http:
        adapter = OpenAiModeration(
            http,
            api_key=key,
            model=settings.moderation_model,
            text_breaker=CircuitBreaker(),
            image_breaker=CircuitBreaker(),
            deadline=settings.timeout_seconds,
        )
        for name, text, recording in MODERATION_SAMPLES:
            started = time.perf_counter()
            result = await adapter.check_text(text)
            seconds = time.perf_counter() - started
            if isinstance(result, Unavailable):
                report.failed = True
                report.lines.append(f"moderation {name}: НЕДОСТУПНО ({result.reason.value})")
                continue
            top = sorted(result.scores.items(), key=lambda item: -item[1])[:2]
            scores = ", ".join(f"{category} {score:.2f}" for category, score in top)
            report.lines.append(
                f"moderation {name}: flagged={result.flagged} [{scores}] ({seconds * 1000:.0f} ms)"
            )
            if recording is not None and result.flagged:  # запись — только настоящий пример
                recorder.save(record, f"openai_moderation_{recording}.json", report)


async def _classifier(
    settings: AiSettings,
    key: str,
    record: Path | None,
    report: SmokeReport,
    transport: httpx2.AsyncBaseTransport | None,
) -> None:
    recorder = _Recorder()
    async with anthropic.AsyncAnthropic(
        api_key=key,
        timeout=anthropic.Timeout(settings.timeout_seconds, connect=5.0),
        max_retries=1,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=transport, event_hooks={"response": [recorder]}
        ),
    ) as client:
        adapter = AnthropicPolicyClassifier(
            client,
            model=settings.classifier_model,
            breaker=CircuitBreaker(),
            deadline=settings.timeout_seconds,
        )
        for kind, text, expected, recording in CLASSIFIER_SAMPLES:
            started = time.perf_counter()
            verdict = await adapter.classify(text, kind=kind)
            seconds = time.perf_counter() - started
            if isinstance(verdict, Unavailable):
                report.failed = True
                report.lines.append(f"classifier {kind.value}: НЕДОСТУПНО ({verdict.reason.value})")
                continue
            note = "" if verdict.label is expected else f" — ожидалось {expected.value}"
            report.lines.append(
                f"classifier {kind.value}: {verdict.label.value} {verdict.confidence:.2f}{note}"
                f" «{verdict.explanation}» ({seconds:.1f} s)"
            )
            if recording is not None and verdict.label is expected:  # тесты ждут эту метку
                recorder.save(record, recording, report)
