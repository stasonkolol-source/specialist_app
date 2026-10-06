"""GET /client-config 🔓 (DEVELOPMENT_PLAN 1.1, 1.5a; ARCHITECTURE §8.5): что клиент читает первым.

Минимальные версии (426), публичные флаги (сегмент «Вещи», техработы), версии правовых
документов и их тексты (S48). Ответ одинаков для всех: тексты — на всех языках, какие есть,
поэтому язык запроса ответ не меняет. Кэшируется: ETag + If-None-Match → 304.

Тексты — 99,5 % ответа (~28 KB), а нужны только S48: Mini App просит конфиг без них
(`?legal_documents=false`) и берёт их отдельным запросом GET /legal-documents, когда открывает
правила. Без параметра конфиг — с текстами, как раньше: выкаченные клиенты не ломаются.
"""

from collections.abc import Mapping
from datetime import date
from typing import Annotated

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.platform.config.cache import ClientConfigCache
from app.platform.config.port import CLIENT_CONFIG_MAX_AGE
from app.platform.http.caching import NOT_MODIFIED, cached_json
from app.platform.kernel.localized import Locale
from app.platform.legal.port import LegalDocument, LegalEdition, LegalLibrary
from app.platform.settings import AppSettings, TelegramSettings

log = structlog.get_logger(__name__)

router = APIRouter(tags=["platform"])
MAX_AGE_SECONDS = CLIENT_CONFIG_MAX_AGE


class LegalTextOut(BaseModel):
    title: str
    body: str
    """Markdown (CommonMark и таблицы GFM) без заголовка первого уровня и без HTML."""


class LegalDocumentOut(BaseModel):
    version: str
    """Та же версия, что в `legal_versions`: с ней identity сверяет согласие."""
    published_on: date
    """Дата редакции."""
    texts: dict[Locale, LegalTextOut]
    """Тексты по языкам. ru есть всегда; sr-Cyrl и sr-Latn — когда есть перевод (K41). Нет
    языка интерфейса — клиент показывает ru с пометкой."""

    @classmethod
    def of(cls, edition: LegalEdition) -> LegalDocumentOut:
        return cls(
            version=edition.version,
            published_on=edition.published_on,
            texts={
                locale: LegalTextOut(title=text.title, body=text.body)
                for locale, text in edition.texts.items()
            },
        )


class ClientConfigOut(BaseModel):
    min_versions: dict[str, str]
    """Минимальная версия клиента по платформе (tma, ios, android): старше — 426."""
    flags: dict[str, bool]
    legal_versions: dict[str, str]
    """Действующие версии правовых документов (terms, privacy): клиент сверяет согласие."""
    legal_documents: dict[str, LegalDocumentOut]
    """Тексты действующих версий (S48), ключи — как в `legal_versions`. Версии без текста
    здесь нет: клиент покажет «документ недоступен», а не чужую редакцию. С
    `?legal_documents=false` — пусто: тексты отдаёт GET /legal-documents."""
    support_username: str | None
    """Аккаунт поддержки в Telegram без `@` (K23, Q25): «Написать в поддержку» S47 и экспорт
    данных S43; null — контакт ещё не назначен, кнопки «скоро»."""


class LegalDocumentsOut(BaseModel):
    documents: dict[str, LegalDocumentOut]
    """Тексты действующих версий (S48), ключи — как в `legal_versions` client-config. Версии
    без текста здесь нет: клиент покажет «документ недоступен», а не чужую редакцию."""


@router.get(
    "/client-config",
    response_model=ClientConfigOut,
    responses=NOT_MODIFIED,
)
@inject
async def get_client_config(
    *,
    request: Request,
    cache: FromDishka[ClientConfigCache],
    app: FromDishka[AppSettings],
    telegram: FromDishka[TelegramSettings],
    library: FromDishka[LegalLibrary],
    legal_documents: Annotated[
        bool,
        Query(
            description="false — без текстов правовых документов: их отдаёт GET /legal-documents"
        ),
    ] = True,
) -> Response:
    snapshot = await cache.get()
    body = ClientConfigOut(
        min_versions={**app.min_client_versions, **snapshot.min_versions},
        flags=snapshot.public_flags(),
        legal_versions=dict(snapshot.legal_versions),
        legal_documents=_documents(snapshot.legal_versions, library) if legal_documents else {},
        support_username=telegram.support_username,
    ).model_dump(mode="json")
    return cached_json(request, body, max_age=MAX_AGE_SECONDS)


@router.get(
    "/legal-documents",
    response_model=LegalDocumentsOut,
    responses=NOT_MODIFIED,
)
@inject
async def get_legal_documents(
    request: Request,
    cache: FromDishka[ClientConfigCache],
    library: FromDishka[LegalLibrary],
) -> Response:
    """Тексты действующих редакций для S48 — отдельно от client-config: первому запуску не нужны.
    Те же версии, что в `legal_versions` client-config, и тот же кэш: ETag, max-age 60."""
    snapshot = await cache.get()
    body = LegalDocumentsOut(documents=_documents(snapshot.legal_versions, library))
    return cached_json(request, body.model_dump(mode="json"), max_age=MAX_AGE_SECONDS)


def _documents(versions: Mapping[str, str], library: LegalLibrary) -> dict[str, LegalDocumentOut]:
    documents: dict[str, LegalDocumentOut] = {}
    for key, version in sorted(versions.items()):
        edition = library.edition(LegalDocument(key), version) if key in LegalDocument else None
        if edition is None:
            # версию включили в админке раньше, чем выложили её текст: чинить конфигурацию
            log.error("legal_text_missing", document=key, version=version)
            continue
        documents[key] = LegalDocumentOut.of(edition)
    return documents
