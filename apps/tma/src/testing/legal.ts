// Правовые тексты для тестов и e2e (DEVELOPMENT_PLAN 1.5a): черновики backend/content/legal в том
// виде, в каком их отдаёт GET /client-config (backend/src/app/platform/legal/files.py) с
// настройками по умолчанию — без front matter и заметок владельца, с подстановками. Только Node.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { LegalDocumentOut } from '@sosed/api-client';

const LEGAL_DIR = resolve(import.meta.dirname, '../../../../backend/content/legal');

/** Как LegalSettings и AppSettings backend по умолчанию: владелец ещё не решил (K22). */
const PLACEHOLDERS: Record<string, string> = {
  appName: 'Сосед',
  OPERATOR_NAME: '[TODO K22: оператор данных — решает владелец, ADR-0018]',
  CONTACT_EMAIL: '[TODO K22: почта поддержки — решает владелец, K23]',
};

export function draftDocument(
  document: 'terms' | 'privacy',
  version = 'draft-1',
): LegalDocumentOut {
  const raw = readFileSync(`${LEGAL_DIR}/${document}/${version}/ru.md`, 'utf8');
  const date = /^---\ndate: (\d{4}-\d{2}-\d{2})\n---\n/.exec(raw);
  if (!date?.[1]) throw new Error(`${document}/${version}: нет даты редакции`);
  const text = raw
    .slice(date[0].length)
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => PLACEHOLDERS[name] ?? '')
    .trim();
  const [heading = '', ...rest] = text.split('\n');
  return {
    version,
    published_on: date[1],
    texts: {
      ru: {
        title: heading.replace(/^# /, '').trim(),
        body: `${rest
          .join('\n')
          .replace(/\n{3,}/g, '\n\n')
          .trim()}\n`,
      },
    },
  };
}
