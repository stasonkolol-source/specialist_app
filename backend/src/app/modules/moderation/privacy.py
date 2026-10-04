"""Выгрузка данных moderation (DEVELOPMENT_PLAN 2.12b): жалобы пользователя, санкции и кейсы о
нём.

Из кейсов не выгружаются заметки модератора и доказательства: это материалы разбора, а не
данные, которые пользователь дал сам; решение, причина и даты — выгружаются. Сигналы риска —
антифрод, не выгружаются (законный интерес, §7.10). Решения и жалобы хранятся 3–5 лет по
исковой давности: правило понадобится не раньше 2029 года, срок отсчитывается от решения.
"""

from app.modules.moderation.infrastructure.models import CaseRow, ReportRow, SanctionRow
from app.platform.privacy.registry import ExportTable, export_section

export_section(
    "moderation",
    ExportTable(ReportRow, lambda user: ReportRow.reporter_id == user),
    ExportTable(SanctionRow, lambda user: SanctionRow.user_id == user),
    ExportTable(
        CaseRow,
        lambda user: CaseRow.subject_id == user,
        exclude=frozenset({"notes", "evidence", "media_ids", "assigned_to", "decided_by"}),
    ),
)
