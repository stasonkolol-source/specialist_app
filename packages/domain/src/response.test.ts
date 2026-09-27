import { describe, expect, it } from 'vitest';

import {
  RESPONSE_STATUSES,
  canTransitionResponse,
  firstResponseId,
  isActiveResponse,
  responseClientActions,
  responsePerformerActions,
  responseTab,
} from './response.ts';

describe('отклик', () => {
  it('активные — только submitted, viewed, shortlisted', () => {
    expect(RESPONSE_STATUSES.filter(isActiveResponse)).toEqual([
      'submitted',
      'viewed',
      'shortlisted',
    ]);
  });

  it('отмена сделки возвращает невыбранных в viewed, отменённый accepted — в declined или withdrawn', () => {
    expect(canTransitionResponse('not_selected', 'viewed')).toBe(true);
    expect(canTransitionResponse('accepted', 'declined')).toBe(true);
    expect(canTransitionResponse('accepted', 'withdrawn')).toBe(true);
    expect(canTransitionResponse('accepted', 'viewed')).toBe(false);
    expect(canTransitionResponse('submitted', 'accepted')).toBe(false);
    expect(canTransitionResponse('declined', 'viewed')).toBe(false);
  });

  it('действия клиента и исполнителя', () => {
    expect(responseClientActions('viewed')).toEqual(['choose', 'write', 'shortlist', 'decline']);
    expect(responseClientActions('shortlisted')).not.toContain('shortlist');
    expect(responseClientActions('declined')).toEqual([]);
    expect(responsePerformerActions('submitted')).toEqual(['withdraw']);
    expect(responsePerformerActions('accepted')).toEqual(['open_deal']);
    expect(responsePerformerActions('not_selected')).toEqual([]);
  });

  it('вкладки «Мои отклики»', () => {
    expect(RESPONSE_STATUSES.map(responseTab)).toEqual([
      'active',
      'active',
      'active',
      'selected',
      'not_selected',
      'archive',
      'not_selected',
    ]);
  });

  it('«откликнулся первым» — самый ранний отклик', () => {
    const responses = [
      { id: 'b', createdAt: '2026-09-27T10:05:00Z' },
      { id: 'a', createdAt: '2026-09-27T10:01:00Z' },
      { id: 'c', createdAt: '2026-09-27T10:09:00Z' },
    ];
    expect(firstResponseId(responses)).toBe('a');
    expect(firstResponseId([])).toBeNull();
  });
});
