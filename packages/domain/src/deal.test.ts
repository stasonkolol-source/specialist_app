import { describe, expect, it } from 'vitest';

import { canTransitionDeal, dealActions } from './deal.ts';

const NOW = new Date('2026-09-27T12:00:00Z');

describe('сделка', () => {
  it('переходы', () => {
    expect(canTransitionDeal('proposed', 'agreed')).toBe(true);
    expect(canTransitionDeal('agreed', 'disputed')).toBe(true);
    expect(canTransitionDeal('disputed', 'completed')).toBe(true);
    expect(canTransitionDeal('proposed', 'completed')).toBe(false);
    expect(canTransitionDeal('completed', 'cancelled')).toBe(false);
  });

  it('«Договорились» подтверждает вторая сторона', () => {
    expect(dealActions({ status: 'proposed', role: 'client', proposedByMe: true }, NOW)).toEqual([
      'chat',
    ]);
    expect(dealActions({ status: 'proposed', role: 'performer' }, NOW)).toEqual([
      'confirm',
      'decline',
      'chat',
    ]);
  });

  it('в agreed: выполнено (один раз), отмена, спор, контакт', () => {
    expect(dealActions({ status: 'agreed', role: 'client' }, NOW)).toEqual([
      'complete',
      'cancel',
      'dispute',
      'share_contact',
      'chat',
    ]);
    expect(
      dealActions({ status: 'agreed', role: 'client', completedByMe: true }, NOW),
    ).not.toContain('complete');
  });

  it('спор: открывший отзывает, вторая сторона отвечает', () => {
    expect(
      dealActions({ status: 'disputed', role: 'client', disputeOpenedByMe: true }, NOW),
    ).toContain('withdraw_dispute');
    expect(dealActions({ status: 'disputed', role: 'performer' }, NOW)).toContain(
      'respond_dispute',
    );
  });

  it('отзыв — только клиент и только 14 дней после завершения', () => {
    const completedAt = '2026-09-20T12:00:00Z';
    expect(dealActions({ status: 'completed', role: 'client', completedAt }, NOW)).toEqual([
      'review',
      'chat',
    ]);
    expect(dealActions({ status: 'completed', role: 'performer', completedAt }, NOW)).toEqual([
      'chat',
    ]);
    expect(
      dealActions({ status: 'completed', role: 'client', completedAt, hasReview: true }, NOW),
    ).toEqual(['chat']);
    const late = new Date('2026-10-04T12:00:01Z');
    expect(dealActions({ status: 'completed', role: 'client', completedAt }, late)).toEqual([
      'chat',
    ]);
  });

  it('отменённую сделку клиент может отметить «не пришёл»', () => {
    expect(dealActions({ status: 'cancelled', role: 'client' }, NOW)).toEqual(['report_no_show']);
    expect(dealActions({ status: 'cancelled', role: 'performer' }, NOW)).toEqual([]);
  });
});
