"""AI-проверки без ключей (K25, K26 — после MVP, решение владельца 2026-10-05; план 2.4).

- `Stub*` — dev и тесты: провайдеров не зовут и за них себя не выдают. Модерация всё
  пропускает, классификатор узнаёт только то, что видит детектор контактов и предоплаты
  (так в dev видно, как работает конвейер).
- `No*` — stage и прод без ключа: адаптер честно отвечает «ключа нет» (`NO_KEY`). Конвейер
  текста сигналом это не считает — текст решают стоп-правила, детектор и выборка уровня 0
  (moderation/domain/pipeline.py); фото без проверки идёт к модератору: кейс P2, фото видно
  до решения (moderation/domain/images.py). Сбой провайдера с ключом — по-прежнему к человеку
  (ADR-0016). Второго проверяющего изображений нет нигде (Q20: по умолчанию «пока без него» —
  сработавшие изображения решает модератор).
"""

from app.platform.ai.port import (
    ContentKind,
    ModerationResult,
    PolicyLabel,
    PolicyVerdict,
    Unavailable,
    UnavailableReason,
)
from app.platform.text.contact_masking import find_contacts, find_prepayment

STUB_NOTE = "проверка без ключа AI: заглушка"
NO_KEY = Unavailable(UnavailableReason.NO_KEY)


class StubModeration:
    async def check_text(self, text: str) -> ModerationResult:  # noqa: ARG002 — всё пропускает
        return ModerationResult(flagged=False)

    async def check_image(self, url: str) -> ModerationResult:  # noqa: ARG002
        return ModerationResult(flagged=False)


class StubPolicyClassifier:
    async def classify(self, text: str, *, kind: ContentKind) -> PolicyVerdict:  # noqa: ARG002
        if find_prepayment(text):
            return PolicyVerdict(
                label=PolicyLabel.PREPAYMENT_SCAM, confidence=0.6, explanation=STUB_NOTE
            )
        if find_contacts(text):
            return PolicyVerdict(
                label=PolicyLabel.CONTACT_LEAK, confidence=0.6, explanation=STUB_NOTE
            )
        return PolicyVerdict(label=PolicyLabel.OK, confidence=0.9, explanation=STUB_NOTE)


class NoModeration:
    async def check_text(self, text: str) -> Unavailable:  # noqa: ARG002 — нет ключа
        return NO_KEY

    async def check_image(self, url: str) -> Unavailable:  # noqa: ARG002
        return NO_KEY


class NoPolicyClassifier:
    async def classify(self, text: str, *, kind: ContentKind) -> Unavailable:  # noqa: ARG002
        return NO_KEY


class NoSecondaryImage:
    async def check(self, url: str) -> Unavailable:  # noqa: ARG002 — Q20: пока без него
        return Unavailable(UnavailableReason.NOT_CONFIGURED)
