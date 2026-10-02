import { describe, expect, it } from 'vitest';

import type { JobDraft } from './draft.ts';
import {
  DRAFT_TTL_MS,
  amountOf,
  budgetProblems,
  jobInOf,
  newDraft,
  parseDraft,
  whatProblems,
  whenProblems,
} from './draft.ts';

/** 2 октября 2026, 12:00 по Белграду. */
const NOW = new Date('2026-10-02T10:00:00Z');

function ready(patch: Partial<JobDraft> = {}): JobDraft {
  return {
    ...newDraft('draft-key-1', NOW, ['ru']),
    title: '  Повесить люстру  ',
    description: 'Потолок бетонный, крюк есть.',
    categoryId: 42,
    categoryName: 'Люстры',
    photos: [{ id: 'media-1', thumb: null }],
    when: 'today',
    slot: '18-21',
    cityId: 1,
    districtId: 7,
    address: ' Народног фронта 25, кв. 14 ',
    budgetType: 'fixed',
    budgetMin: '5 000',
    ...patch,
  };
}

describe('черновик в хранилище', () => {
  it('туда и обратно', () => {
    const draft = ready();
    expect(parseDraft(JSON.stringify(draft), NOW)).toEqual(draft);
  });

  it('испорченный, чужой версии или старше недели — нет', () => {
    expect(parseDraft(null, NOW)).toBeNull();
    expect(parseDraft('{oops', NOW)).toBeNull();
    expect(parseDraft(JSON.stringify({ ...ready(), version: 2 }), NOW)).toBeNull();
    const old = new Date(NOW.getTime() + DRAFT_TTL_MS + 1);
    expect(parseDraft(JSON.stringify(ready()), old)).toBeNull();
  });
});

describe('шаги', () => {
  it('S20a: заголовок от пяти символов и категория', () => {
    expect(whatProblems(ready())).toEqual([]);
    expect(whatProblems(ready({ title: ' Ой ', categoryId: null }))).toEqual(['title', 'category']);
  });

  it('S20b: когда и район; своя дата — впереди', () => {
    expect(whenProblems(ready(), NOW)).toEqual([]);
    expect(whenProblems(ready({ when: null, districtId: null }), NOW)).toEqual([
      'when',
      'district',
    ]);
    const past = ready({ when: 'date', day: '2026-10-01', time: '10:00' });
    expect(whenProblems(past, NOW)).toEqual(['date']);
  });

  it('S20c: сумма, «до» больше «от», договорная — без сумм', () => {
    expect(budgetProblems(ready({ budgetMin: '' }))).toEqual(['amount']);
    expect(budgetProblems(ready({ budgetType: 'range', budgetMax: '4000' }))).toEqual(['range']);
    expect(budgetProblems(ready({ budgetType: 'negotiable', budgetMin: '' }))).toEqual([]);
    expect(amountOf('1 500')).toBe(1500);
    expect(amountOf('0')).toBeNull();
  });
});

describe('тело POST /jobs', () => {
  it('из готового черновика — в пара и по Белграду', () => {
    expect(jobInOf(ready(), NOW)).toEqual({
      title: 'Повесить люстру',
      description: 'Потолок бетонный, крюк есть.',
      category_id: 42,
      urgency: 'today',
      preferred_from: '2026-10-02T16:00:00.000Z',
      preferred_to: '2026-10-02T19:00:00.000Z',
      budget_type: 'fixed',
      budget_min: 500_000,
      budget_max: null,
      budget_unit: 'work',
      city_id: 1,
      district_id: 7,
      address_private: 'Народног фронта 25, кв. 14',
      languages: ['ru'],
      media_ids: ['media-1'],
    });
  });

  it('договорная — без сумм, пустой адрес — null', () => {
    const body = jobInOf(ready({ budgetType: 'negotiable', address: '  ' }), NOW);
    expect([body?.budget_min, body?.budget_max, body?.address_private]).toEqual([
      null,
      null,
      null,
    ]);
  });

  it('недоделанный черновик не отправляется', () => {
    expect(jobInOf(ready({ categoryId: null }), NOW)).toBeNull();
    expect(jobInOf(ready({ cityId: null }), NOW)).toBeNull();
  });
});
