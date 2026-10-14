"""Сигналы риска при регистрации (подписчик UserRegistered; ARCHITECTURE §7.10, §13.3).

- Повторная регистрация после удаления аккаунта: тот же Telegram удалял аккаунт в последние
  12 месяцев — сигнал `reregistered_after_deletion`. С санкциями у прежнего аккаунта — вес выше:
  так «отмывают» рейтинг и баны. Данные прежнего аккаунта не возвращаются.
- Имя из Telegram похоже на контакт или ник (identity заменила его на «Сосед», B3) — сигнал
  `contact_leak` об аккаунте: вход не отклоняли, но попытка вывести контакт в имя — факт.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.moderation.application.ports import RiskSignals
from app.modules.moderation.domain.risk import RiskSignal, RiskSignalKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

WEIGHT_AFTER_SANCTIONS: Final = 3.0
"""Удалял аккаунт с санкциями или подтверждёнными жалобами **[Допущение]**."""
NAME_SOURCE: Final = "telegram_name"
"""Где нашли контакт: `details.source` сигнала `contact_leak` при регистрации."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordReregistrationCommand:
    user_id: UserId
    reregistered: bool
    had_sanctions: bool
    contact_in_name: bool = False


class RecordReregistration:
    def __init__(self, uow: UnitOfWork, signals: RiskSignals) -> None:
        self._uow, self._signals = uow, signals

    async def __call__(self, cmd: RecordReregistrationCommand) -> bool:
        """Записан ли хоть один сигнал."""
        found: list[RiskSignal] = []
        if cmd.reregistered:
            kind = RiskSignalKind.REREGISTERED_AFTER_DELETION
            found.append(
                RiskSignal(
                    user_id=cmd.user_id,
                    kind=kind,
                    weight=WEIGHT_AFTER_SANCTIONS if cmd.had_sanctions else 1.0,
                    details={"had_sanctions": cmd.had_sanctions},
                    dedupe_key=f"{kind}:{cmd.user_id}",
                )
            )
        if cmd.contact_in_name:
            kind = RiskSignalKind.CONTACT_LEAK
            found.append(
                RiskSignal(
                    user_id=cmd.user_id,
                    kind=kind,
                    details={"source": NAME_SOURCE},
                    dedupe_key=f"{kind}:{NAME_SOURCE}:{cmd.user_id}",
                )
            )
        if not found:
            return False
        async with self._uow:
            return await self._signals.add(found) > 0
