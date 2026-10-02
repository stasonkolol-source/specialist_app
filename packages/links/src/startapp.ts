// Коды startapp для t.me/<bot>?startapp=<код> (ARCHITECTURE §11.4): ≤ 64 символов [A-Za-z0-9_-], без `_tgr_`.
import { base62ToUuid, uuidToBase62 } from './base62.ts';

export const START_PARAM_MAX_LENGTH = 64;
const START_PARAM_RE = /^[A-Za-z0-9_-]+$/;
/** Префикс партнёрской программы Telegram: такие параметры не наши. */
const TELEGRAM_RESERVED_PREFIX = '_tgr_';

/** Сущности с экраном в Mini App; тип → префикс кода. */
export const ENTITY_PREFIX = {
  job: 'j',
  specialist: 's',
  chat: 'c',
  deal: 'd',
} as const;
export type EntityType = keyof typeof ENTITY_PREFIX;

/** Правовые документы: `l_terms`, `l_privacy` — вкладка S48 (команды бота /terms и /privacy). */
export const LEGAL_DOCUMENTS = ['terms', 'privacy'] as const;
export type LegalDocument = (typeof LEGAL_DOCUMENTS)[number];

/** Свои разделы: `m_jobs` — «Мои заявки» S22 (команда бота /jobs). */
export const MINE_SECTIONS = ['jobs'] as const;
export type MineSection = (typeof MINE_SECTIONS)[number];

/** Раздел «Вещи» (после MVP): префиксы зарезервированы, `gh` и `h` — разные типы. */
export const RESERVED_CODES = ['g', 'gu', 'gh', 'gs', 'gc'] as const;
export type ReservedCode = (typeof RESERVED_CODES)[number];

/** Реферальный код или код атрибуции канала — только суффикс `_r<code>`. */
const REF_RE = /^[A-Za-z0-9]+$/;
/** Значение зарезервированного кода (`gs_<id>`, `gc_<code>`): без `_`, чтобы разбор был однозначным. */
const PAYLOAD_RE = /^[A-Za-z0-9-]+$/;

export type StartLink =
  | { type: EntityType; id: string; ref?: string }
  | { type: 'home'; ref?: string }
  /** `n` — мастер новой заявки S20a (команда бота /new). */
  | { type: 'new_job'; ref?: string }
  | { type: 'mine'; section: MineSection; ref?: string }
  | { type: 'legal'; document: LegalDocument; ref?: string }
  | { type: 'reserved'; code: ReservedCode; value?: string; ref?: string };

const PREFIX_TO_ENTITY = new Map<string, EntityType>(
  Object.entries(ENTITY_PREFIX).map(([type, prefix]) => [prefix, type as EntityType]),
);

export class StartParamError extends Error {
  override name = 'StartParamError';
}

/** Синтаксис Telegram: длина, алфавит, не партнёрский `_tgr_`. */
export function isValidStartParam(value: string): boolean {
  return (
    value.length > 0 &&
    value.length <= START_PARAM_MAX_LENGTH &&
    START_PARAM_RE.test(value) &&
    !value.startsWith(TELEGRAM_RESERVED_PREFIX)
  );
}

export function encodeStartParam(link: StartLink): string {
  let code: string;
  if (link.type === 'home') {
    code = 'h';
  } else if (link.type === 'new_job') {
    code = 'n';
  } else if (link.type === 'mine') {
    if (!isMineSection(link.section)) {
      throw new StartParamError(`Недопустимый раздел «${String(link.section)}»`);
    }
    code = `m_${link.section}`;
  } else if (link.type === 'legal') {
    if (!isLegalDocument(link.document)) {
      throw new StartParamError(`Недопустимый документ «${String(link.document)}»`);
    }
    code = `l_${link.document}`;
  } else if (link.type === 'reserved') {
    const needsValue = link.code !== 'gh';
    if (needsValue !== (link.value !== undefined) || (link.value && !PAYLOAD_RE.test(link.value))) {
      throw new StartParamError(`Недопустимое значение для ${link.code}: «${link.value ?? ''}»`);
    }
    code = link.value === undefined ? link.code : `${link.code}_${link.value}`;
  } else {
    code = `${ENTITY_PREFIX[link.type]}_${uuidToBase62(link.id)}`;
  }
  if (link.ref !== undefined) {
    if (!REF_RE.test(link.ref))
      throw new StartParamError(`Недопустимый реферальный код «${link.ref}»`);
    code += `_r${link.ref}`;
  }
  if (!isValidStartParam(code)) throw new StartParamError(`Недопустимый код startapp «${code}»`);
  return code;
}

function isLegalDocument(value: string | undefined): value is LegalDocument {
  return LEGAL_DOCUMENTS.some((document) => document === value);
}

function isMineSection(value: string | undefined): value is MineSection {
  return MINE_SECTIONS.some((section) => section === value);
}

function parseCode([head, ...rest]: string[]): StartLink | null {
  if (head === undefined) return null;
  if (head === 'h') return rest.length === 0 ? { type: 'home' } : null;
  if (head === 'n') return rest.length === 0 ? { type: 'new_job' } : null;
  if (head === 'm') {
    const [section] = rest;
    return rest.length === 1 && isMineSection(section) ? { type: 'mine', section } : null;
  }
  if (head === 'l') {
    const [document] = rest;
    return rest.length === 1 && isLegalDocument(document) ? { type: 'legal', document } : null;
  }
  const entity = PREFIX_TO_ENTITY.get(head);
  if (entity) {
    const id = rest.length === 1 ? base62ToUuid(rest[0] ?? '') : null;
    return id ? { type: entity, id } : null;
  }
  const code = RESERVED_CODES.find((c) => c === head);
  if (!code) return null;
  if (code === 'gh') return rest.length === 0 ? { type: 'reserved', code } : null;
  const [value] = rest;
  return rest.length === 1 && value && PAYLOAD_RE.test(value)
    ? { type: 'reserved', code, value }
    : null;
}

/** Разбор кода; `null` — неизвестный или битый код (приложение открывает главную). */
export function parseStartParam(value: string | null | undefined): StartLink | null {
  if (!value || !isValidStartParam(value)) return null;
  const parts = value.split('_');
  const plain = parseCode(parts);
  if (plain) return plain;
  // `…_r<code>` — суффикс, а не тип: пробуем отрезать его
  const last = parts.at(-1) ?? '';
  const ref = last.slice(1);
  if (parts.length < 2 || !last.startsWith('r') || !REF_RE.test(ref)) return null;
  const link = parseCode(parts.slice(0, -1));
  return link ? { ...link, ref } : null;
}
