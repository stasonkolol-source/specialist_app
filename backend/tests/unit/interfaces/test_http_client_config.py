"""GET /client-config без БД и сборка правовых текстов (DEVELOPMENT_PLAN 1.1, 1.5a)."""

from datetime import date

import pytest
from structlog.testing import capture_logs

from app.interfaces.http.client_config import _documents
from app.platform.kernel.localized import Locale
from app.platform.legal.port import LegalDocument, LegalEdition, LegalText
from app.platform.settings import Settings
from tests.plugins.http import http_client

pytestmark = pytest.mark.unit

TERMS = LegalEdition(
    document=LegalDocument.TERMS,
    version="draft-1",
    published_on=date(2026, 9, 27),
    texts={Locale.RU: LegalText(title="Правила площадки «Соседи»", body="Текст.\n")},
)


class FakeLibrary:
    def edition(self, document: LegalDocument, version: str) -> LegalEdition | None:
        return TERMS if (document, version) == (TERMS.document, TERMS.version) else None

    def versions(self, document: LegalDocument) -> frozenset[str]:
        return frozenset({TERMS.version}) if document is TERMS.document else frozenset()


def test_documents_carry_texts_of_current_versions() -> None:
    documents = _documents({"terms": "draft-1"}, FakeLibrary())
    assert {key: doc.model_dump(mode="json") for key, doc in documents.items()} == {
        "terms": {
            "version": "draft-1",
            "published_on": "2026-09-27",
            "texts": {"ru": {"title": "Правила площадки «Соседи»", "body": "Текст.\n"}},
        }
    }


def test_version_without_text_is_left_out_and_logged() -> None:
    """Версию включили в админке раньше, чем выложили текст: не отдаём чужую редакцию."""
    with capture_logs() as logs:
        documents = _documents(
            {"terms": "draft-9", "privacy": "draft-1", "unknown": "1"}, FakeLibrary()
        )
    assert documents == {}
    assert [(log["event"], log["document"]) for log in logs] == [
        ("legal_text_missing", "privacy"),
        ("legal_text_missing", "terms"),
        ("legal_text_missing", "unknown"),
    ]


async def test_without_database_config_is_served_empty(offline_settings: Settings) -> None:
    """БД недоступна — снимок пуст (fail open, ADR-0021): версий и текстов нет, ответ 200."""
    async with http_client(offline_settings) as client:
        response = await client.get("/api/v1/client-config", headers={"accept-language": "sr"})
        assert response.status_code == 200
        body = response.json()
        assert body["legal_versions"] == {}
        assert body["legal_documents"] == {}
        assert "vary" not in response.headers
        cached = await client.get(
            "/api/v1/client-config", headers={"if-none-match": response.headers["etag"]}
        )
        assert cached.status_code == 304
