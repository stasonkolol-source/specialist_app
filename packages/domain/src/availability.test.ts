import { describe, expect, it } from 'vitest';

import {
  availabilityHour,
  availableUntil,
  businessTime,
  isUpcoming,
  quickHour,
  untilTime,
} from './availability.ts';

/** Момент по Белграду в октябре (UTC+2). */
const belgrade = (hour: number, minute = 0) => new Date(Date.UTC(2026, 9, 1, hour - 2, minute));

describe('availability', () => {
  it('reads the time in Belgrade wherever the phone is', () => {
    expect(businessTime(new Date(Date.UTC(2026, 9, 1, 23, 30)))).toEqual({ hour: 1, minute: 30 });
  });

  it('offers only hours still ahead today', () => {
    expect(isUpcoming(18, belgrade(17, 59))).toBe(true);
    expect(isUpcoming(18, belgrade(18, 0))).toBe(false);
  });

  it('switches on «until 20:00» by default, later — the nearest hour, after 22:00 — nothing', () => {
    expect(quickHour(belgrade(9))).toBe(20);
    expect(quickHour(belgrade(20, 30))).toBe(22);
    expect(quickHour(belgrade(22, 5))).toBeNull();
  });

  it('treats a passed deadline as off and maps deadlines to the artboard options', () => {
    const until = belgrade(20).toISOString();
    expect(availableUntil(until, belgrade(19))).toEqual(belgrade(20));
    expect(availableUntil(until, belgrade(20, 1))).toBeNull();
    expect(availableUntil(null, belgrade(19))).toBeNull();
    expect(availabilityHour(belgrade(20))).toBe(20);
    expect(availabilityHour(belgrade(19, 30))).toBeNull();
    expect(untilTime(18)).toBe('18:00');
  });
});
