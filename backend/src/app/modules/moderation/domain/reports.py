"""Жалобы пользователей (ARCHITECTURE §7.3 `moderation.reports`, ADR-0016 §4, ADR-0018).

Таблица заведена в 2.5a вместе с кейсами (жалоба ведёт к кейсу P1 или P0); приём жалоб —
`POST /reports` в 4.7. `due_at` — срок заявления третьего лица о незаконном контенте
(ст. 20 ZET, два рабочих дня) — задел v1: в MVP такие жалобы идут очередью P1.
"""

from enum import StrEnum


class ReportReason(StrEnum):
    SPAM = "spam"
    FRAUD = "fraud"
    PROHIBITED = "prohibited"
    OFFENSIVE = "offensive"
    FAKE_PROFILE = "fake_profile"
    NO_SHOW = "no_show"
    PERSONAL_DATA = "personal_data"
    DEFAMATION = "defamation"
    COPYRIGHT = "copyright"
    ILLEGAL = "illegal"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"
