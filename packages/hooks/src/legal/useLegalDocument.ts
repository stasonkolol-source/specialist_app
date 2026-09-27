// S48 (DEVELOPMENT_PLAN 1.5a): текст правового документа из client-config — действующая версия,
// с ней человек и соглашается (S02c). Тексты приходят на всех языках, какие есть: смена языка не
// требует запроса. Перевода нет — текст на ru и `translated: false` (до K41).
import type { LegalDocumentOut, LegalTextOut, Locale } from '@sosed/api-client';

import { useClientConfig } from '../config/clientConfig.ts';

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

export function useLegalDocument(key: LegalDocumentKey, locale: Locale) {
  const config = useClientConfig();
  const document = config.data?.legal_documents[key];
  const text = document ? legalText(document, locale) : null;
  return {
    config,
    /** Версия и дата редакции; `undefined` — конфиг не загружен или версии без текста. */
    document,
    text,
    translated: text === null || text.locale === locale,
  };
}
