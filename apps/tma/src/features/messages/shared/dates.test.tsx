// Даты переписки: подпись дня в ленте S30 и время строки списка S29, как в Telegram. Дни — по
// Белграду, а не по часам устройства: полночь в UTC — ещё вчерашний вечер.
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, i18nReady } from '@sosed/i18n';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { dayKey, daysBefore, useDayLabel, useListTime } from './dates.ts';

// понедельник, 5 октября 2026, 10:00 по Белграду (UTC+2)
const NOW = new Date('2026-10-05T08:00:00Z');

/** Хук на языке `locale`: сербские тексты первого экрана догружаются — ждём их. */
async function hook<T>(use: () => T, locale: Locale = 'ru'): Promise<T> {
  const i18n = createI18n({ locale, appName: 'Соседи' });
  await i18nReady(i18n);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
  );
  return renderHook(use, { wrapper }).result.current;
}

describe('days in Belgrade', () => {
  it('counts calendar days, not 24-hour periods', () => {
    // 00:30 по Белграду — уже понедельник, хотя в UTC ещё воскресенье
    expect(dayKey(new Date('2026-10-04T22:30:00Z'))).toBe('2026-10-05');
    expect(daysBefore(new Date('2026-10-04T22:30:00Z'), NOW)).toBe(0);
    expect(daysBefore(new Date('2026-10-04T21:30:00Z'), NOW)).toBe(1);
    // через переход на зимнее время (25 октября) — те же сутки
    expect(daysBefore(new Date('2026-10-24T10:00:00Z'), new Date('2026-10-26T10:00:00Z'))).toBe(2);
  });
});

describe('useDayLabel', () => {
  it('names today and yesterday, other days by date', async () => {
    const label = await hook(useDayLabel);
    expect(label(new Date('2026-10-05T06:00:00Z'), NOW)).toBe('Сегодня');
    expect(label(new Date('2026-10-04T20:00:00Z'), NOW)).toBe('Вчера');
    expect(label(new Date('2026-10-02T10:00:00Z'), NOW)).toBe('2 октября');
    // другой год — с годом, как у остальных дат приложения (format.date)
    expect(label(new Date('2025-12-31T10:00:00Z'), NOW)).toMatch(/^31 декабря 2025/);
  });

  it('speaks Serbian', async () => {
    const label = await hook(useDayLabel, 'sr-Latn');
    expect(label(new Date('2026-10-05T06:00:00Z'), NOW)).toBe('Danas');
    expect(label(new Date('2026-10-04T20:00:00Z'), NOW)).toBe('Juče');
    expect(label(new Date('2026-10-02T10:00:00Z'), NOW)).toBe('2. oktobar');
  });
});

describe('useListTime', () => {
  it('is short, as in Telegram: time, «вчера», weekday, short date', async () => {
    const time = await hook(useListTime);
    expect(time(new Date('2026-10-05T07:05:00Z'), NOW)).toBe('09:05');
    expect(time(new Date('2026-10-04T20:00:00Z'), NOW)).toBe('вчера');
    // пятница и вторник прошлой недели — днём недели, ровно неделя назад — датой
    expect(time(new Date('2026-10-02T10:00:00Z'), NOW)).toBe('пт');
    expect(time(new Date('2026-09-29T10:00:00Z'), NOW)).toBe('вт');
    expect(time(new Date('2026-09-28T10:00:00Z'), NOW)).toBe('28 сент');
    expect(time(new Date('2025-12-31T10:00:00Z'), NOW)).toBe('31.12.25');
  });

  it('speaks Serbian', async () => {
    const time = await hook(useListTime, 'sr-Latn');
    expect(time(new Date('2026-10-04T20:00:00Z'), NOW)).toBe('juče');
    expect(time(new Date('2026-10-02T10:00:00Z'), NOW)).toBe('pet');
    expect(time(new Date('2026-09-28T10:00:00Z'), NOW)).toBe('28. sep');
  });
});
