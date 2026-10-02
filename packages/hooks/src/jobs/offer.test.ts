// Предложение исполнителя S16 и S57: проверка полей, тело запроса в пара, черновик из шаблона,
// «тот же шаблон» и название шаблона из сообщения.
import type { ResponseTemplateOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import {
  emptyOffer,
  offerDraftOf,
  offerIn,
  offerPriceOf,
  offerProblems,
  sameOffer,
  templateTitleOf,
} from './offer.ts';

const TEMPLATE: ResponseTemplateOut = {
  id: 'tpl-1',
  title: 'Могу сегодня',
  message: 'Здравствуйте! Могу сегодня вечером.',
  price: { type: 'from', amount: { amount: 200_000, currency: 'RSD' } },
  availability_note: 'сегодня',
  primary: true,
  updated_at: '2026-10-02T10:00:00Z',
};

describe('offer', () => {
  it('needs a message and an amount unless negotiable', () => {
    expect(offerProblems(emptyOffer())).toEqual(['message', 'amount']);
    expect(offerProblems({ ...emptyOffer(), message: ' ', priceType: 'negotiable' })).toEqual([
      'message',
    ]);
    expect(offerIn(emptyOffer())).toBeNull();
  });

  it('sends trimmed text and the amount in para', () => {
    expect(
      offerIn({ message: ' Могу завтра ', priceType: 'hourly', amount: '1 500', when: ' ' }),
    ).toEqual({
      message: 'Могу завтра',
      price_type: 'hourly',
      price_amount: 150_000,
      availability_note: null,
    });
    expect(
      offerIn({ message: 'Обсудим', priceType: 'negotiable', amount: '900', when: 'Вечером' }),
    ).toEqual({
      message: 'Обсудим',
      price_type: 'negotiable',
      price_amount: null,
      availability_note: 'Вечером',
    });
  });

  it('round-trips a template through the form', () => {
    const draft = offerDraftOf(TEMPLATE);
    expect(draft).toEqual({
      message: 'Здравствуйте! Могу сегодня вечером.',
      priceType: 'from',
      amount: '2000',
      when: 'сегодня',
    });
    expect(sameOffer(draft, TEMPLATE)).toBe(true);
    expect(sameOffer({ ...draft, amount: '2 000' }, TEMPLATE)).toBe(true);
    expect(sameOffer({ ...draft, when: 'завтра' }, TEMPLATE)).toBe(false);
    expect(offerPriceOf(draft)).toEqual(TEMPLATE.price);
    expect(offerPriceOf({ ...draft, amount: '' })).toBeNull();
    expect(offerPriceOf({ ...draft, priceType: 'negotiable' })).toEqual({
      type: 'negotiable',
      amount: null,
    });
  });

  it('titles a template by the first phrase after a greeting', () => {
    expect(templateTitleOf('Здравствуйте! Могу сегодня в 19:00. Инструмент свой.')).toBe(
      'Могу сегодня в 19:00',
    );
    expect(templateTitleOf('Dobar dan! Mogu danas.')).toBe('Mogu danas');
    expect(templateTitleOf('Приеду со своим инструментом')).toBe('Приеду со своим инструментом');
    const long = templateTitleOf(
      'Приеду со своим инструментом и стремянкой, работаю аккуратно и убираю за собой',
    );
    expect(long.length).toBeLessThanOrEqual(40);
    expect(long).toBe('Приеду со своим инструментом и…');
  });
});
