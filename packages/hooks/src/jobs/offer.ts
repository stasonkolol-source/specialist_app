// Предложение исполнителя — форма S16 и шаблон S57 (DEVELOPMENT_PLAN 5.5): сообщение клиенту, цена
// «Фикс / От / За час / Договорная» и «когда смогу». Сумма в поле — цифры RSD, в API — пара.
import type {
  ResponseOfferIn,
  ResponsePriceOut,
  ResponsePriceType,
  ResponseTemplateOut,
} from '@sosed/api-client';
import { paraToRsd, rsdToPara } from '@sosed/domain';

import { amountOf } from './draft.ts';

export const RESPONSE_MESSAGE_MAX = 1500;
export const RESPONSE_AVAILABILITY_MAX = 200;
export const TEMPLATE_TITLE_MAX = 40;
/** Шаблонов у исполнителя: оба — кнопками в уведомлении бота. */
export const TEMPLATES_MAX = 2;

export const RESPONSE_PRICE_TYPES: readonly ResponsePriceType[] = [
  'fixed',
  'from',
  'hourly',
  'negotiable',
];

export interface OfferDraft {
  message: string;
  priceType: ResponsePriceType;
  /** Цифры суммы в RSD, как в поле; у договорной не нужны. */
  amount: string;
  /** «Когда смогу»: «Сегодня, 19:00». */
  when: string;
}

export type OfferProblem = 'message' | 'amount';

export const emptyOffer = (): OfferDraft => ({
  message: '',
  priceType: 'fixed',
  amount: '',
  when: '',
});

export function offerProblems(draft: OfferDraft): OfferProblem[] {
  const problems: OfferProblem[] = [];
  if (!draft.message.trim()) problems.push('message');
  if (draft.priceType !== 'negotiable' && amountOf(draft.amount) === null) problems.push('amount');
  return problems;
}

/** Тело запроса; форма с ошибками — null. */
export function offerIn(draft: OfferDraft): ResponseOfferIn | null {
  if (offerProblems(draft).length > 0) return null;
  const amount = amountOf(draft.amount);
  const when = draft.when.trim();
  return {
    message: draft.message.trim(),
    price_type: draft.priceType,
    price_amount: draft.priceType === 'negotiable' || amount === null ? null : rsdToPara(amount),
    availability_note: when || null,
  };
}

/** Цена черновика для превью «так увидит клиент»; сумма не введена — null. */
export function offerPriceOf(draft: OfferDraft): ResponsePriceOut | null {
  if (draft.priceType === 'negotiable') return { type: 'negotiable', amount: null };
  const amount = amountOf(draft.amount);
  return amount === null
    ? null
    : { type: draft.priceType, amount: { amount: rsdToPara(amount), currency: 'RSD' } };
}

/** Черновик формы из отклика или шаблона: правка S16 и S57, «вставить шаблон». */
export function offerDraftOf(source: {
  message: string;
  price: ResponsePriceOut;
  availability_note?: string | null;
}): OfferDraft {
  return {
    message: source.message,
    priceType: source.price.type,
    amount: source.price.amount ? String(paraToRsd(source.price.amount.amount)) : '',
    when: source.availability_note ?? '',
  };
}

/** Шаблон, вставленный в форму, ещё не правили: подсветка чипа S16. */
export function sameOffer(draft: OfferDraft, template: ResponseTemplateOut): boolean {
  const other = offerDraftOf(template);
  return (
    draft.message.trim() === other.message.trim() &&
    draft.priceType === other.priceType &&
    (draft.priceType === 'negotiable' || amountOf(draft.amount) === amountOf(other.amount)) &&
    draft.when.trim() === other.when.trim()
  );
}

/** Название шаблона из сообщения: «Сохранить как шаблон» на S16 — без лишнего поля, переименовать
 *  можно на S57. Первая фраза после приветствия («Здравствуйте!», «Dobar dan!» — одно-два слова)
 *  без точки в конце, не длиннее 40 знаков — по границе слова. */
export function templateTitleOf(message: string): string {
  const phrases = message
    .trim()
    .split(/(?<=[.!?…])\s+|\n+/)
    .map((phrase) => phrase.trim())
    .filter(Boolean);
  const [first = '', second] = phrases;
  const greeting = second !== undefined && first.split(/\s+/).length <= 2;
  const phrase = (greeting ? second : first).replace(/[.…]+$/, '');
  if (phrase.length <= TEMPLATE_TITLE_MAX) return phrase;
  const cut = phrase.slice(0, TEMPLATE_TITLE_MAX - 1);
  const space = cut.lastIndexOf(' ');
  return `${(space > TEMPLATE_TITLE_MAX / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
