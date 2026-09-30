"""AI-проверки без ключей (K25–K26 ещё не даны; DEVELOPMENT_PLAN 2.4).

- `Stub*` — dev и тесты: провайдеров не зовут и за них себя не выдают. Модерация всё
  пропускает, классификатор узнаёт только то, что видит детектор контактов и предоплаты
  (так в dev видно, как работает конвейер).
- `No*` — stage и прод без ключа: проверка «недоступна», контент идёт в ручную очередь, а не
  публикуется без AI (ADR-0016). Второго проверяющего изображений нет нигде (Q20: по
  умолчанию «пока без него» — сработавшие изображения решает модератор).
"""

from app.platform.ai.port import ContentKind, ModerationResult, PolicyLabel, PolicyVerdict
from app.platform.text.contact_masking import find_contacts, find_prepayment

STUB_NOTE = "проверка без ключа AI: заглушка"


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
    async def check_text(self, text: str) -> ModerationResult:  # noqa: ARG002 — нет ключа
        return ModerationResult.unavailable()

    async def check_image(self, url: str) -> ModerationResult:  # noqa: ARG002
        return ModerationResult.unavailable()


class NoPolicyClassifier:
    async def classify(self, text: str, *, kind: ContentKind) -> PolicyVerdict:  # noqa: ARG002
        return PolicyVerdict.unavailable()


class NoSecondaryImage:
    async def check(self, url: str) -> ModerationResult:  # noqa: ARG002 — Q20: пока без него
        return ModerationResult.unavailable()
