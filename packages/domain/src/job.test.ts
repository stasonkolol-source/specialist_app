import { describe, expect, it } from 'vitest';

import {
  JOB_STATUSES,
  JOB_TRANSITIONS,
  canTransitionJob,
  jobClientActions,
  jobPerformerActions,
  jobTab,
} from './job.ts';
import { responseSlots } from './slots.ts';

describe('заявка: переходы', () => {
  it.each([
    ['draft', 'pending_moderation'],
    ['pending_moderation', 'published'],
    ['pending_moderation', 'rejected'],
    ['rejected', 'pending_moderation'],
    ['published', 'pending_moderation'],
    ['published', 'assigned'],
    ['published', 'closed'],
    ['published', 'expired'],
    ['published', 'removed'],
    ['published', 'published'],
    ['expired', 'published'],
    ['assigned', 'completed'],
    ['assigned', 'published'],
    ['assigned', 'closed'],
  ] as const)('%s → %s разрешён', (from, to) => {
    expect(canTransitionJob(from, to)).toBe(true);
  });

  it.each([
    ['draft', 'published'],
    ['expired', 'closed'],
    ['completed', 'published'],
    ['closed', 'published'],
    ['removed', 'published'],
  ] as const)('%s → %s запрещён', (from, to) => {
    expect(canTransitionJob(from, to)).toBe(false);
  });

  it('терминальные статусы без выходов', () => {
    const terminal = JOB_STATUSES.filter((s) => JOB_TRANSITIONS[s].length === 0);
    expect(terminal).toEqual(['completed', 'closed', 'removed']);
  });
});

describe('заявка: действия', () => {
  it('клиент продлевает опубликованную заявку не больше 3 раз', () => {
    expect(jobClientActions({ status: 'published', extensionsCount: 2 })).toContain('extend');
    expect(jobClientActions({ status: 'published', extensionsCount: 3 })).not.toContain('extend');
    expect(jobClientActions({ status: 'expired', extensionsCount: 0 })).toEqual(['republish']);
    expect(jobClientActions({ status: 'expired', extensionsCount: 3 })).toEqual([]);
  });

  it('в работе — сделка и закрытие', () => {
    expect(jobClientActions({ status: 'assigned', extensionsCount: 0 })).toEqual([
      'open_deal',
      'close',
    ]);
    expect(jobClientActions({ status: 'closed', extensionsCount: 0 })).toEqual([]);
  });

  it('исполнитель откликается, пока есть места и отклика нет', () => {
    const open = responseSlots({ responsesCount: 3 });
    const full = responseSlots({ responsesCount: 5 });
    expect(jobPerformerActions({ status: 'published', slots: open, hasResponded: false })).toEqual([
      'respond',
      'share',
      'hide',
      'report',
    ]);
    expect(
      jobPerformerActions({ status: 'published', slots: full, hasResponded: false }),
    ).not.toContain('respond');
    expect(
      jobPerformerActions({ status: 'published', slots: open, hasResponded: true }),
    ).not.toContain('respond');
    expect(jobPerformerActions({ status: 'assigned', slots: open, hasResponded: false })).toEqual(
      [],
    );
  });

  it('вкладки «Мои заявки»', () => {
    expect(JOB_STATUSES.map((s) => [s, jobTab(s)])).toEqual([
      ['draft', 'active'],
      ['pending_moderation', 'active'],
      ['published', 'active'],
      ['rejected', 'active'],
      ['assigned', 'in_work'],
      ['completed', 'completed'],
      ['closed', 'archive'],
      ['expired', 'active'],
      ['removed', 'archive'],
    ]);
  });
});
