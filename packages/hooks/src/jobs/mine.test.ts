// Своя заявка S23 и итог S21: когда перечитывать заявку (на проверке — всё реже, открытую — вместе с
// откликами) и отличает ли новая версия заявки чужую правку от смены статуса (ADV-07).
import type { JobOut } from '@sosed/api-client';
import { describe, expect, it } from 'vitest';

import { REVIEW_POLL_MS, reviewPollMs } from './jobs.ts';
import { RESPONSES_POLL_MS, ownJobPollMs, sameOwnerFields } from './mine.ts';

const job = (patch: Partial<JobOut> = {}): JobOut => ({
  id: '0199dd60-0000-7000-8000-000000000001',
  viewer_role: 'owner',
  status: 'pending_moderation',
  visibility: 'public',
  title: 'Повесить люстру',
  description: 'Потолок бетонный',
  content_lang: 'ru',
  category_id: 104,
  urgency: 'today',
  preferred_from: '2026-10-02T16:00:00.000Z',
  preferred_to: '2026-10-02T19:00:00.000Z',
  budget_type: 'fixed',
  budget_min: { amount: 500_000, currency: 'RSD' },
  budget_max: null,
  budget_unit: 'work',
  city_id: 1,
  district_id: 11,
  point_public: null,
  point_exact: null,
  address_private: 'Народног фронта 25',
  languages: ['ru'],
  media_ids: [],
  photos: [],
  client: null,
  max_responses: 5,
  responses_count: 0,
  my_response: null,
  extensions_count: 0,
  views_count: 0,
  notified_count: 0,
  new_responses: 0,
  moderation_note: null,
  version: 1,
  created_at: '2026-10-02T10:00:00Z',
  published_at: null,
  expires_at: null,
  closed_at: null,
  close_reason: null,
  ...patch,
});

describe('reviewPollMs', () => {
  it('re-reads a job on review sooner first, then less often (SMOKE-2)', () => {
    const pending = job();
    expect([1, 2, 3, 4, 5, 9].map((updates) => reviewPollMs(pending, updates))).toEqual([
      ...REVIEW_POLL_MS,
      REVIEW_POLL_MS.at(-1),
    ]);
  });

  it('stops once the job left the review', () => {
    expect(reviewPollMs(job({ status: 'published' }), 1)).toBe(false);
    expect(reviewPollMs(job({ status: 'rejected' }), 1)).toBe(false);
    expect(reviewPollMs(undefined, 0)).toBe(false);
  });
});

describe('ownJobPollMs', () => {
  it('re-reads an open job with its responses, one on review — on the review schedule', () => {
    expect(ownJobPollMs(job({ status: 'published' }), 7)).toBe(RESPONSES_POLL_MS);
    expect(ownJobPollMs(job(), 1)).toBe(REVIEW_POLL_MS[0]);
    expect(ownJobPollMs(job({ status: 'closed' }), 1)).toBe(false);
  });
});

describe('sameOwnerFields', () => {
  it('ignores what the system changes: status, version, counters', () => {
    const base = job();
    const published = job({
      status: 'published',
      version: 2,
      published_at: '2026-10-02T10:00:01Z',
      responses_count: 1,
      views_count: 3,
    });
    expect(sameOwnerFields(published, base)).toBe(true);
  });

  it('sees an edit made elsewhere', () => {
    expect(sameOwnerFields(job({ title: 'Повесить две люстры', version: 2 }), job())).toBe(false);
    const budget = job({ budget_min: { amount: 700_000, currency: 'RSD' } });
    expect(sameOwnerFields(budget, job())).toBe(false);
  });
});
