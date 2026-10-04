"""Отчёт покрытия тестов прав (DEVELOPMENT_PLAN 8.4, ARCHITECTURE §13.1 «IDOR»).

Каждая операция API с id ресурса в пути классифицирована здесь:
- `owner` — ресурс владельца или участника: у операции есть тест «чужой ресурс» (другой
  пользователь получает 404 или 403), и тест помечен `@pytest.mark.authz`;
- `mixed` — публичный, пока опубликован, иначе только владельцу: тоже с тестом `authz`;
- `actor` — действие над видимым ресурсом от своего имени (избранное, скрыть, блокировка):
  чужие данные не затрагиваются, субъект — principal;
- `public` — справочник или публичная карточка.

Новая операция с `{id}` в пути без строки здесь роняет тест: права решаются явно.
Прогон всех тестов прав: `uv run pytest -m authz` (они integration — нужен Docker).
"""

import json
import re
from pathlib import Path
from typing import Literal

import pytest

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[2]
Scope = Literal["owner", "mixed", "actor", "public"]

DEALS = "tests/integration/test_deals.py"
DISPUTES = "tests/integration/test_disputes.py"
RESPONSES = "tests/integration/test_responses.py"
JOBS = "tests/integration/test_jobs.py"
INVITES = "tests/integration/test_invites.py"
MESSAGING = "tests/integration/test_messaging.py"
CHAT_DEALS = "tests/integration/test_chat_deals.py"
MEDIA = "src/app/modules/media/tests/api/test_uploads.py"
STRANGERS = "test_authz_strangers_cannot_touch_responses_deals_and_invites"
REVIEW_INVITES = (
    "tests/integration/test_review_invites.py"
    "::test_authz_strangers_cannot_revoke_and_nobody_reviews_himself_or_twice"
)

INVENTORY: dict[tuple[str, str], tuple[Scope, str]] = {
    # сделки и споры
    ("GET", "/deals/{deal_id}"): (
        "owner",
        f"{DEALS}::test_accept_creates_an_agreed_deal_and_assigns_the_job",
    ),
    ("POST", "/deals/{deal_id}/confirm"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/deals/{deal_id}/decline"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/deals/{deal_id}/complete"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/deals/{deal_id}/cancel"): (
        "owner",
        f"{DEALS}::test_cancel_reason_is_chosen_by_a_party",
    ),
    ("POST", "/deals/{deal_id}/review"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("GET", "/deals/{deal_id}/card"): (
        "owner",
        "tests/integration/test_deal_card.py::test_deal_card_for_both_sides",
    ),
    ("POST", "/deals/{deal_id}/dispute"): (
        "owner",
        f"{DISPUTES}::test_dispute_opens_a_p1_case_and_wakes_the_other_party",
    ),
    ("POST", "/deals/{deal_id}/dispute/respond"): (
        "owner",
        f"{DISPUTES}::test_authz_outsider_cannot_answer_or_withdraw_a_dispute",
    ),
    ("POST", "/deals/{deal_id}/dispute/withdraw"): (
        "owner",
        f"{DISPUTES}::test_authz_outsider_cannot_answer_or_withdraw_a_dispute",
    ),
    ("POST", "/reviews/{review_id}/reply"): (
        "owner",
        "tests/integration/test_reviews.py"
        "::test_specialist_replies_once_and_the_reply_shows_after_its_check",
    ),
    # «отзывы до платформы»: ссылка — секрет; чужая, отозванная, истёкшая и использованная — 404
    ("DELETE", "/me/profile/review-invites/{token}"): ("owner", REVIEW_INVITES),
    ("GET", "/review-invites/{token}"): ("mixed", REVIEW_INVITES),
    ("POST", "/review-invites/{token}"): ("mixed", REVIEW_INVITES),
    # заявки
    ("GET", "/jobs/{job_id}"): (
        "mixed",
        f"{JOBS}::test_new_job_waits_for_review_and_only_the_owner_sees_it",
    ),
    ("PATCH", "/jobs/{job_id}"): (
        "owner",
        f"{JOBS}::test_stale_version_is_refused_and_strangers_cannot_touch_the_job",
    ),
    ("DELETE", "/jobs/{job_id}"): (
        "owner",
        f"{JOBS}::test_stale_version_is_refused_and_strangers_cannot_touch_the_job",
    ),
    ("POST", "/jobs/{job_id}/close"): (
        "owner",
        f"{JOBS}::test_stale_version_is_refused_and_strangers_cannot_touch_the_job",
    ),
    ("POST", "/jobs/{job_id}/extend"): (
        "owner",
        f"{JOBS}::test_stale_version_is_refused_and_strangers_cannot_touch_the_job",
    ),
    ("GET", "/jobs/{job_id}/responses"): (
        "owner",
        f"{RESPONSES}::test_clean_response_is_shown_to_the_owner_after_the_check",
    ),
    ("POST", "/jobs/{job_id}/responses"): (
        "mixed",
        f"{RESPONSES}::test_responding_refuses_own_full_closed_and_repeated",
    ),
    ("POST", "/jobs/{job_id}/invites"): (
        "owner",
        f"{INVITES}::test_inviting_refuses_strangers_own_hidden_and_too_many",
    ),
    ("GET", "/jobs/{job_id}/invites"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("GET", "/jobs/{job_id}/response-cards"): (
        "owner",
        "tests/integration/test_my_job.py::test_new_responses_become_seen_on_the_response_cards",
    ),
    ("POST", "/jobs/{job_id}/hide"): ("actor", "hide_job: только видимая заявка, своё скрытие"),
    ("PUT", "/me/favorites/job/{job_id}"): ("actor", "своё избранное"),
    ("DELETE", "/me/favorites/job/{job_id}"): ("actor", "своё избранное"),
    ("POST", "/specialists/{profile_id}/requests"): (
        "mixed",
        f"{INVITES}::test_direct_request_is_seen_and_answered_only_by_the_specialist",
    ),
    # отклики и шаблоны
    ("GET", "/responses/{response_id}"): (
        "owner",
        f"{RESPONSES}::test_revising_and_withdrawing_bump_the_job_version",
    ),
    ("PATCH", "/responses/{response_id}"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/responses/{response_id}/withdraw"): (
        "owner",
        f"{RESPONSES}::test_revising_and_withdrawing_bump_the_job_version",
    ),
    ("POST", "/responses/{response_id}/accept"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/responses/{response_id}/shortlist"): ("owner", f"{DEALS}::{STRANGERS}"),
    ("POST", "/responses/{response_id}/decline"): (
        "owner",
        f"{DEALS}::test_shortlist_and_decline",
    ),
    ("PATCH", "/me/response-templates/{template_id}"): (
        "owner",
        f"{RESPONSES}::test_templates_are_two_at_most_and_the_first_is_primary",
    ),
    ("DELETE", "/me/response-templates/{template_id}"): (
        "owner",
        f"{RESPONSES}::test_templates_are_two_at_most_and_the_first_is_primary",
    ),
    ("PATCH", "/me/job-alerts/{alert_id}"): (
        "owner",
        "tests/integration/test_job_alerts.py::test_alert_crud_limit_and_week_count",
    ),
    ("DELETE", "/me/job-alerts/{alert_id}"): (
        "owner",
        "tests/integration/test_job_alerts.py::test_alert_crud_limit_and_week_count",
    ),
    # медиа
    ("POST", "/media/uploads/{media_id}/parts"): (
        "owner",
        f"{MEDIA}::test_foreign_media_is_not_found",
    ),
    ("POST", "/media/uploads/{media_id}/complete"): (
        "owner",
        f"{MEDIA}::test_foreign_media_is_not_found",
    ),
    ("GET", "/media/{media_id}"): ("owner", f"{MEDIA}::test_foreign_media_is_not_found"),
    ("DELETE", "/media/{media_id}"): ("owner", f"{MEDIA}::test_foreign_media_is_not_found"),
    # диалоги
    ("GET", "/conversations/{conversation_id}/messages"): (
        "owner",
        f"{MESSAGING}::test_response_conversation_starts_with_the_offer_once",
    ),
    ("POST", "/conversations/{conversation_id}/messages"): (
        "owner",
        f"{MESSAGING}::test_stranger_closed_and_restricted_cannot_write",
    ),
    ("POST", "/conversations/{conversation_id}/read"): (
        "owner",
        f"{MESSAGING}::test_unread_until_read",
    ),
    ("POST", "/conversations/{conversation_id}/deal"): (
        "owner",
        f"{CHAT_DEALS}::test_proposal_terms_are_checked",
    ),
    ("POST", "/conversations/{conversation_id}/share-contact"): (
        "owner",
        f"{CHAT_DEALS}::test_contact_is_shared_after_the_deal_and_only_ones_own",
    ),
    # кабинет исполнителя
    ("PATCH", "/me/profile/services/{service_id}"): (
        "owner",
        "src/app/modules/pricing/tests/api/test_price_list.py"
        "::test_authz_foreign_service_cannot_be_changed_or_removed",
    ),
    ("DELETE", "/me/profile/services/{service_id}"): (
        "owner",
        "src/app/modules/pricing/tests/api/test_price_list.py"
        "::test_authz_foreign_service_cannot_be_changed_or_removed",
    ),
    ("PATCH", "/me/profile/portfolio/{item_id}"): (
        "owner",
        "src/app/modules/specialists/tests/api/test_portfolio.py"
        "::test_authz_foreign_work_cannot_be_captioned_or_removed",
    ),
    ("DELETE", "/me/profile/portfolio/{item_id}"): (
        "owner",
        "src/app/modules/specialists/tests/api/test_portfolio.py"
        "::test_authz_foreign_work_cannot_be_captioned_or_removed",
    ),
    # свои связи с чужими публичными ресурсами
    ("PUT", "/me/favorites/profile/{profile_id}"): ("actor", "своё избранное"),
    ("DELETE", "/me/favorites/profile/{profile_id}"): ("actor", "своё избранное"),
    ("PUT", "/me/blocks/{user_id}"): ("actor", "своя блокировка"),
    ("DELETE", "/me/blocks/{user_id}"): ("actor", "снимается только своя блокировка"),
    # публичное: справочники и опубликованные карточки (скрытые и санкционные — 404)
    ("GET", "/cities/{city_id}/districts"): ("public", "справочник"),
    ("GET", "/specialists/{profile_id}"): (
        "mixed",
        "tests/integration/test_specialist_card.py::test_hidden_profile_is_not_found",
    ),
    ("GET", "/specialists/{profile_id}/services"): ("public", "видимость как у карточки"),
    ("GET", "/specialists/{profile_id}/portfolio"): ("public", "видимость как у карточки"),
    ("GET", "/specialists/{profile_id}/reviews"): ("public", "видимость как у карточки"),
}


def _operations() -> set[tuple[str, str]]:
    spec = json.loads((BACKEND / "openapi.json").read_text(encoding="utf-8"))
    return {
        (method.upper(), path.removeprefix("/api/v1"))
        for path, item in spec["paths"].items()
        if "{" in path
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }


def test_every_operation_with_a_resource_id_is_classified() -> None:
    operations = _operations()
    assert operations - INVENTORY.keys() == set(), "новая операция с id: решите права здесь"
    assert INVENTORY.keys() - operations == set(), "операции больше нет: уберите строку"


@pytest.mark.parametrize(
    ("operation", "reference"),
    [
        (f"{method} {path}", reference)
        for (method, path), (scope, reference) in INVENTORY.items()
        if scope in ("owner", "mixed")
    ],
)
def test_owner_operations_have_a_marked_foreign_resource_test(
    operation: str, reference: str
) -> None:
    file, _, name = reference.partition("::")
    source = (BACKEND / file).read_text(encoding="utf-8")
    match = re.search(rf"((?:^@.*\n)*)^(?:async )?def {name}\(", source, re.M)
    assert match is not None, f"{operation}: нет теста {reference}"
    assert "@pytest.mark.authz" in match[1], f"{operation}: {name} без @pytest.mark.authz"
