"""Выгрузка данных reviews (DEVELOPMENT_PLAN 2.12b): отзывы, написанные пользователем и о нём,
и просьбы оставить отзыв по его сделкам."""

from sqlalchemy import or_

from app.modules.reviews.infrastructure.models import ReviewRequestRow, ReviewRow
from app.platform.privacy.registry import ExportTable, export_section

export_section(
    "reviews",
    ExportTable(
        ReviewRow, lambda user: or_(ReviewRow.author_id == user, ReviewRow.subject_user_id == user)
    ),
    ExportTable(
        ReviewRequestRow,
        lambda user: or_(ReviewRequestRow.client_id == user, ReviewRequestRow.performer_id == user),
    ),
)
