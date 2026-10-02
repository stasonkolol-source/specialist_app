"""Повторная регистрация после удаления аккаунта (подписчик UserRegistered; ARCHITECTURE
§7.10, §13.3): тот же Telegram удалял аккаунт в последние 12 месяцев — сигнал риска
`reregistered_after_deletion`. С санкциями у прежнего аккаунта — вес выше: так «отмывают»
рейтинг и баны. Данные прежнего аккаунта не возвращаются.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.moderation.application.ports import RiskSignals
from app.modules.moderation.domain.risk import RiskSignal, RiskSignalKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

WEIGHT_AFTER_SANCTIONS: Final = 3.0
"""Удалял аккаунт с санкциями или подтверждёнными жалобами **[Допущение]**."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordReregistrationCommand:
    user_id: UserId
    reregistered: bool
    had_sanctions: bool


class RecordReregistration:
    def __init__(self, uow: UnitOfWork, signals: RiskSignals) -> None:
        self._uow, self._signals = uow, signals

    async def __call__(self, cmd: RecordReregistrationCommand) -> bool:
        """Записан ли сигнал."""
        if not cmd.reregistered:
            return False
        kind = RiskSignalKind.REREGISTERED_AFTER_DELETION
        signal = RiskSignal(
            user_id=cmd.user_id,
            kind=kind,
            weight=WEIGHT_AFTER_SANCTIONS if cmd.had_sanctions else 1.0,
            details={"had_sanctions": cmd.had_sanctions},
            dedupe_key=f"{kind}:{cmd.user_id}",
        )
        async with self._uow:
            return await self._signals.add([signal]) > 0
