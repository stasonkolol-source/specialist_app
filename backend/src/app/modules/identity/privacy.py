"""Сроки хранения и выгрузка данных identity (ARCHITECTURE §7.10, DEVELOPMENT_PLAN 2.12b).

Правило: хэши Telegram ID и телефона удалённых аккаунтов — 12 месяцев. Выгрузка: аккаунт,
способы входа, сессии (без хэшей токенов), ограничения, согласия, роли, история статусов,
запросы на удаление, сделки для уровня доверия, блокировки.
"""

from app.modules.identity.application.use_cases.purge_identity_hashes import (
    PurgeIdentityHashes,
    PurgeIdentityHashesCommand,
)
from app.modules.identity.infrastructure.models import (
    AuthIdentityRow,
    CompletedDealRow,
    ConsentRow,
    DeletionRequestRow,
    RestrictionRow,
    SessionRow,
    StatusHistoryRow,
    UserBlockRow,
    UserRoleRow,
    UserRow,
)
from app.platform.privacy.registry import ExportTable, RetentionRun, export_section, retention_rule


@retention_rule("identity.deleted_identity_hashes", keep="12 мес. после удаления аккаунта")
async def deleted_identity_hashes(run: RetentionRun) -> int:
    async with run.container() as request:
        purge = await request.get(PurgeIdentityHashes)
        return await purge(PurgeIdentityHashesCommand(now=run.now))


export_section(
    "identity",
    ExportTable(UserRow, lambda user: UserRow.id == user),
    ExportTable(AuthIdentityRow, lambda user: AuthIdentityRow.user_id == user),
    ExportTable(
        SessionRow,
        lambda user: SessionRow.user_id == user,
        exclude=frozenset({"refresh_token_hash", "previous_refresh_hash"}),
    ),
    ExportTable(RestrictionRow, lambda user: RestrictionRow.user_id == user),
    ExportTable(ConsentRow, lambda user: ConsentRow.user_id == user),
    ExportTable(UserRoleRow, lambda user: UserRoleRow.user_id == user),
    ExportTable(StatusHistoryRow, lambda user: StatusHistoryRow.user_id == user),
    ExportTable(DeletionRequestRow, lambda user: DeletionRequestRow.user_id == user),
    ExportTable(CompletedDealRow, lambda user: CompletedDealRow.user_id == user),
    ExportTable(UserBlockRow, lambda user: UserBlockRow.blocker_id == user),
)
