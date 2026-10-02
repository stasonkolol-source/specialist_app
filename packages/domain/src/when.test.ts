import { describe, expect, it } from 'vitest';

import {
  TODAY_SLOTS,
  addDays,
  businessDay,
  businessMoment,
  isSlotOpen,
  jobWhen,
  slotKey,
  slotOf,
} from './when.ts';

/** 2 октября 2026, 12:00 по Белграду (летнее время, UTC+2). */
const NOON = new Date('2026-10-02T10:00:00Z');
const [, , , EVENING] = TODAY_SLOTS;

describe('время по Белграду', () => {
  it('день — по Белграду, а не по UTC', () => {
    expect(businessDay(new Date('2026-10-02T21:59:00Z'))).toBe('2026-10-02');
    expect(businessDay(new Date('2026-10-02T22:30:00Z'))).toBe('2026-10-03');
  });

  it('момент по белградским часам — летом и зимой', () => {
    expect(businessMoment('2026-10-02', 18).toISOString()).toBe('2026-10-02T16:00:00.000Z');
    expect(businessMoment('2026-12-01', 18, 30).toISOString()).toBe('2026-12-01T17:30:00.000Z');
  });

  it('дни через границу месяца', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-10-02', -2)).toBe('2026-09-30');
  });
});

describe('удобное время сегодня', () => {
  it('окно открыто, пока не кончилось', () => {
    expect(isSlotOpen(EVENING, NOON)).toBe(true);
    expect(isSlotOpen(TODAY_SLOTS[0], NOON)).toBe(false); // 9–12 в полдень уже прошло
    expect(isSlotOpen(EVENING, new Date('2026-10-02T19:00:00Z'))).toBe(false); // 21:00
  });

  it('ключ окна туда и обратно', () => {
    expect(slotKey(EVENING)).toBe('18-21');
    expect(slotOf('18-21')).toBe(EVENING);
    expect(slotOf('7-9')).toBeNull();
  });
});

describe('срочность заявки из выбора', () => {
  it('срочно и на неделе — без времени', () => {
    expect(jobWhen({ choice: 'asap' }, NOON)).toEqual({
      urgency: 'asap',
      preferredFrom: null,
      preferredTo: null,
    });
    expect(jobWhen({ choice: 'week' }, NOON)?.urgency).toBe('this_week');
  });

  it('сегодня в окно 18–21', () => {
    expect(jobWhen({ choice: 'today', slot: EVENING }, NOON)).toEqual({
      urgency: 'today',
      preferredFrom: new Date('2026-10-02T16:00:00Z'),
      preferredTo: new Date('2026-10-02T19:00:00Z'),
    });
  });

  it('своя дата: сегодня, на неделе, позже', () => {
    const at = (day: string) => jobWhen({ choice: 'date', day, time: '10:00' }, NOON);
    expect(at('2026-10-03')).toEqual({
      urgency: 'this_week',
      preferredFrom: new Date('2026-10-03T08:00:00Z'),
      preferredTo: null,
    });
    expect(at('2026-10-20')?.urgency).toBe('flexible');
    expect(jobWhen({ choice: 'date', day: '2026-10-02', time: '18:00' }, NOON)?.urgency).toBe(
      'today',
    );
  });

  it('прошлое, слишком далёкое или неполное — нет', () => {
    expect(jobWhen({ choice: 'date', day: '2026-10-02', time: '09:00' }, NOON)).toBeNull();
    expect(jobWhen({ choice: 'date', day: '2026-12-01', time: '10:00' }, NOON)).toBeNull();
    expect(jobWhen({ choice: 'date', day: '2026-10-03', time: null }, NOON)).toBeNull();
    expect(jobWhen({ choice: 'date', day: null, time: '10:00' }, NOON)).toBeNull();
  });
});
