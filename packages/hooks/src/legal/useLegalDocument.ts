// S48 (DEVELOPMENT_PLAN 1.5a): текст правового документа — действующая версия, с ней человек и
// соглашается (S02c). Тексты — своим запросом GET /legal-documents, только когда их открыли:
// первому запуску они не нужны, а в client-config были 99,5 % ответа. Тексты приходят на всех
// языках, какие есть: смена языка не требует запроса. Перевода нет — текст на ru и
// `translated: false` (до K41).
import type { LegalDocumentOut, LegalTextOut, Locale } from '@sosed/api-client';
import { getSystemGetLegalDocumentsQueryOptions } from '@sosed/api-client';
import { useQuery } from '@tanstack/react-query';

import { CLIENT_CONFIG_STALE_MS, useClientConfig } from '../config/clientConfig.ts';

/** Документы S48; ключи — как в `legal_versions` client-config. */
export const LEGAL_DOCUMENTS = ['terms', 'privacy'] as const;
export type LegalDocumentKey = (typeof LEGAL_DOCUMENTS)[number];

export function isLegalDocument(value: unknown): value is LegalDocumentKey {
  return LEGAL_DOCUMENTS.some((key) => key === value);
}

/** Исходник документов — ru: он есть в каждой редакции. */
const SOURCE_LOCALE: Locale = 'ru';

export interface LegalTextView extends LegalTextOut {
  /** Язык текста; не совпал с запрошенным — перевода пока нет. */
  locale: Locale;
}

/** Текст на языке интерфейса, иначе исходник ru. */
export function legalText(document: LegalDocumentOut, locale: Locale): LegalTextView | null {
  for (const candidate of [locale, SOURCE_LOCALE]) {
    const text = document.texts[candidate];
    if (text) return { ...text, locale: candidate };
  }
  return null;
}

/** Ключ и свежесть текстов — одни у хука и у предзагрузки по намерению (app/prefetch.ts); кэш
 *  сервера тот же, что у client-config. */
export function legalDocumentsQueryOptions() {
  return getSystemGetLegalDocumentsQueryOptions({ query: { staleTime: CLIENT_CONFIG_STALE_MS } });
}

export function useLegalDocument(key: LegalDocumentKey, locale: Locale) {
  const query = useQuery(legalDocumentsQueryOptions());
  // фронтенд и backend выкатываются порознь (ADR-0015): старый backend не знает /legal-documents
  // (404) и `?legal_documents=false` — тексты тогда приходят в самом client-config. `?.` у
  // legal_documents: конфиг ещё более старого backend без поля даёт «Документ недоступен»
  const config = useClientConfig();
  const document = query.data?.documents[key] ?? config.data?.legal_documents?.[key];
  const text = document ? legalText(document, locale) : null;
  return {
    query,
    /** Версия и дата редакции; `undefined` — тексты не загружены или версии без текста. */
    document,
    text,
    translated: text === null || text.locale === locale,
  };
}
