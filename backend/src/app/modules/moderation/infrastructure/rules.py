"""Словарь контент-правил в БД: импорт из сидов и снимок для проверки (DEVELOPMENT_PLAN 2.4).

Импорт (`cli seed`, seeds/moderation/content_rules.yaml) идемпотентен:
- правило определяет пара (kind, pattern); новое — вставляется с `origin = seed`;
- строки сида файл задаёт целиком, включая `is_active`: правка файла меняет язык, действие
  и категорию, а правило, которого больше нет в файле, выключается (строка остаётся для
  истории кейсов, где оно сработало);
- строки админки (`origin = admin`, 2.7b) сид не трогает, даже если в файле то же правило;
- два импорта одновременно (два деплоя) не мешают друг другу: advisory lock транзакции.

Снимок (`CachedRuleSource`) живёт в процессе, как ClientConfigCache: правка словаря доходит
до всех процессов за TTL, без деплоя. БД недоступна или не ответила за REFRESH_TIMEOUT —
остаётся прошлый снимок, повтор через RETRY; пока один запрос обновляет снимок, остальные
получают прошлый, не дожидаясь. Правило, которое не компилируется, пропускается с
предупреждением в логе; пустой словарь (сид не загружен) — тоже предупреждение.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from datetime import timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.moderation.application.dto import ImportRulesResult
from app.modules.moderation.domain.rules import ContentRule, RuleSet
from app.modules.moderation.infrastructure.models import ContentRuleRow, RuleOrigin
from app.platform.db.port import UnitOfWork

log = structlog.get_logger(__name__)

TTL = timedelta(seconds=60)
RETRY = timedelta(seconds=5)
REFRESH_TIMEOUT = timedelta(seconds=5)
"""Чтение словаря из БД: дольше — остаётся прошлый снимок (соединение пула может ждать 30 с)."""
IMPORT_LOCK = 0x6D6F645F72756C65
"""pg_advisory_xact_lock импорта словаря: «mod_rule» в hex."""


class SqlRuleWriter:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def import_seed(self, rules: Sequence[ContentRule]) -> ImportRulesResult:
        self._uow.require_active()  # advisory lock транзакции — только внутри UoW
        await self._session.execute(select(func.pg_advisory_xact_lock(IMPORT_LOCK)))
        stored = {
            (row.kind, row.pattern): row
            for row in (await self._session.scalars(select(ContentRuleRow))).all()
        }
        created = updated = unchanged = skipped = deactivated = 0
        for rule in rules:
            row = stored.pop((rule.kind, rule.pattern), None)
            wanted = (rule.lang, rule.action, rule.category, rule.active)
            if row is None:
                self._session.add(
                    ContentRuleRow(
                        pattern=rule.pattern,
                        kind=rule.kind,
                        lang=rule.lang,
                        action=rule.action,
                        category=rule.category,
                        is_active=rule.active,
                        origin=RuleOrigin.SEED,
                    )
                )
                created += 1
            elif row.origin is RuleOrigin.ADMIN:
                skipped += 1
            elif (row.lang, row.action, row.category, row.is_active) == wanted:
                unchanged += 1
            else:
                row.lang, row.action, row.category, row.is_active = wanted
                updated += 1
        for row in stored.values():  # правила сида, которых больше нет в файле
            if row.origin is RuleOrigin.SEED and row.is_active:
                row.is_active = False
                deactivated += 1
        await self._session.flush()
        return ImportRulesResult(
            created=created,
            updated=updated,
            unchanged=unchanged,
            deactivated=deactivated,
            skipped=skipped,
        )


class CachedRuleSource:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        *,
        ttl: timedelta = TTL,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maker, self._ttl, self._monotonic = maker, ttl.total_seconds(), monotonic
        self._snapshot = RuleSet()
        self._expires = 0.0
        self._rejected: frozenset[int | None] = frozenset()
        self._loaded = False
        self._lock = asyncio.Lock()

    async def current(self) -> RuleSet:
        if self._monotonic() < self._expires:
            return self._snapshot
        if self._loaded and self._lock.locked():
            return self._snapshot  # обновляет другой запрос: прошлый снимок, без ожидания
        async with self._lock:
            if self._monotonic() >= self._expires:
                await self._refresh()
        return self._snapshot

    def invalidate(self) -> None:
        self._expires = 0.0

    async def _refresh(self) -> None:
        try:
            async with asyncio.timeout(REFRESH_TIMEOUT.total_seconds()), self._maker() as session:
                rows = (
                    await session.scalars(select(ContentRuleRow).where(ContentRuleRow.is_active))
                ).all()
        except (SQLAlchemyError, TimeoutError) as exc:
            log.warning("content_rules_unavailable", error=type(exc).__name__)
            self._expires = self._monotonic() + RETRY.total_seconds()
            return
        try:
            ruleset = RuleSet(
                ContentRule(
                    id=row.id,
                    pattern=row.pattern,
                    kind=row.kind,
                    lang=row.lang,
                    action=row.action,
                    category=row.category,
                )
                for row in rows
            )
        except Exception:  # словарь, который не собрался, не должен выключить все проверки
            log.exception("content_rules_build_failed")
            self._expires = self._monotonic() + RETRY.total_seconds()
            return
        rejected = frozenset(rule.id for rule, _ in ruleset.rejected)
        for rule, reason in ruleset.rejected:
            if rule.id not in self._rejected:  # в лог — один раз, а не каждые TTL
                log.warning("content_rule_invalid", rule_id=rule.id, reason=reason)
        if len(ruleset) == 0 and (not self._loaded or len(self._snapshot) > 0):
            # словарь не загружен (`cli seed`): работают только детекторы, block-правил нет
            log.warning("content_rules_empty")
        self._snapshot, self._rejected, self._loaded = ruleset, rejected, True
        self._expires = self._monotonic() + self._ttl
