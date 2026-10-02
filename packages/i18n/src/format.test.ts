// Форматтеры во всех трёх локалях. `_` в ожидаемых строках — неразрывный пробел.
import { BUDGET_BUCKETS, rsdToPara } from '@sosed/domain';
import { describe, expect, it } from 'vitest';

import { NBSP, createFormat, formatMessage } from './format.ts';
import type { Locale } from './locale.ts';

const nb = (s: string) => s.replaceAll('_', NBSP);
const ru = createFormat('ru');
const lat = createFormat('sr-Latn');
const cyr = createFormat('sr-Cyrl');

describe('деньги', () => {
  it('минимальные единицы → «5 000 RSD» в ru и «5.000 RSD» в sr', () => {
    expect(ru.money(rsdToPara(5_000))).toBe(nb('5_000_RSD'));
    expect(lat.money(rsdToPara(5_000))).toBe(nb('5.000_RSD'));
    expect(cyr.money(rsdToPara(5_000))).toBe(nb('5.000_RSD'));
    expect(ru.money(rsdToPara(1_234_567))).toBe(nb('1_234_567_RSD'));
    expect(ru.money(rsdToPara(800))).toBe(nb('800_RSD'));
    expect(ru.money(1_250)).toBe(nb('12,50_RSD'));
  });

  it('диапазон — валюта один раз', () => {
    expect(ru.moneyRange(rsdToPara(4_000), rsdToPara(6_000))).toBe(nb('4_000–6_000_RSD'));
    expect(lat.moneyRange(rsdToPara(4_000), rsdToPara(6_000))).toBe(nb('4.000–6.000_RSD'));
  });
});

describe('цены как на макетах', () => {
  const p = (rsd: number) => rsdToPara(rsd);
  it.each([
    [{ type: 'fixed', min: p(5_000) }, '5_000_RSD'],
    [{ type: 'from', min: p(2_000), unit: 'visit' }, 'от_2_000_RSD за выезд'],
    [{ type: 'from', min: p(1_800), unit: 'item' }, 'от_1_800_RSD за предмет'],
    [{ type: 'hourly', min: p(1_000) }, '1_000_RSD/час'],
    [{ type: 'from', min: p(3_500), unit: 'hour' }, 'от_3_500_RSD/час'],
    [{ type: 'per_unit', min: p(1_500), unit: 'lesson' }, '1_500_RSD/урок'],
    [{ type: 'range', min: p(4_000), max: p(6_000) }, '4_000–6_000_RSD'],
    [{ type: 'range', min: 0, max: p(3_000) }, 'до_3_000_RSD'],
    [{ type: 'negotiable' }, 'договорная'],
  ] as const)('%o → %s', (price, expected) => {
    expect(ru.price(price)).toBe(nb(expected));
  });

  it('сербский', () => {
    expect(lat.price({ type: 'from', min: p(2_000), unit: 'visit' })).toBe(
      nb('od_2.000_RSD po dolasku'),
    );
    expect(cyr.price({ type: 'hourly', min: p(1_000) })).toBe(nb('1.000_RSD/сат'));
    expect(lat.price({ type: 'negotiable' })).toBe('po dogovoru');
  });
});

describe('бакеты бюджета', () => {
  it('ru и sr', () => {
    expect(BUDGET_BUCKETS.map(ru.budgetBucket)).toEqual(
      ['до_2_000', '2–5_тыс.', '5–10_тыс.', '10–30_тыс.', '30–100_тыс.', '100_тыс.+'].map(nb),
    );
    expect(BUDGET_BUCKETS.map(lat.budgetBucket)).toEqual(
      ['do_2.000', '2–5_hilj.', '5–10_hilj.', '10–30_hilj.', '30–100_hilj.', '100_hilj.+'].map(nb),
    );
  });
});

describe('рейтинг', () => {
  it('всегда с одним знаком после запятой', () => {
    expect(ru.rating(4.9)).toBe('4,9');
    expect(ru.rating(5)).toBe('5,0');
    expect(lat.rating(4.66)).toBe('4,7');
  });
});

describe('расстояние', () => {
  it.each([
    [1_500, '≈_1,5_км', '≈_1,5_km'],
    [2_000, '≈_2_км', '≈_2_km'],
    [1_230, '≈_1,2_км', '≈_1,2_km'],
    [12_400, '≈_12_км', '≈_12_km'],
    [600, '≈_600_м', '≈_600_m'],
    [40, '≈_100_м', '≈_100_m'],
    [960, '≈_1_км', '≈_1_km'],
  ])('%d м', (meters, ruText, latText) => {
    expect(ru.distance(meters)).toBe(nb(ruText));
    expect(lat.distance(meters)).toBe(nb(latText));
  });
});

describe('даты в Europe/Belgrade', () => {
  // 27.09.2026 12:00 по Белграду (UTC+2, летнее время)
  const now = new Date('2026-09-27T10:00:00Z');

  it('время и дата по Белграду, а не по поясу устройства', () => {
    expect(ru.time(new Date('2026-09-27T17:00:00Z'))).toBe('19:00');
    expect(ru.date(new Date('2026-10-12T08:00:00Z'), now)).toBe('12 октября');
    expect(lat.date(new Date('2026-10-12T08:00:00Z'), now)).toBe('12. oktobar');
    expect(cyr.date(new Date('2026-10-12T08:00:00Z'), now)).toBe('12. октобар');
    expect(ru.date(new Date('2027-01-05T08:00:00Z'), now)).toBe('5 января 2027 г.');
    // 23:30 UTC 27.09 — уже 28.09 в Белграде
    expect(ru.calendar(new Date('2026-09-27T23:30:00Z'), now)).toBe(nb('завтра в_01:30'));
  });

  it('дата с годом — как в редакции документа на S48', () => {
    expect(ru.fullDate(new Date('2026-09-27T10:00:00Z'))).toBe('27 сентября 2026');
    expect(lat.fullDate(new Date('2026-09-27T10:00:00Z'))).toBe('27. septembar 2026.');
    expect(cyr.fullDate(new Date('2026-09-27T10:00:00Z'))).toBe('27. септембар 2026.');
  });

  it('«сегодня в 19:00»', () => {
    expect(ru.calendar(new Date('2026-09-27T17:00:00Z'), now)).toBe(nb('сегодня в_19:00'));
    expect(lat.calendar(new Date('2026-09-27T17:00:00Z'), now)).toBe(nb('danas u_19:00'));
    expect(ru.calendar(new Date('2026-10-12T16:00:00Z'), now)).toBe(nb('12 октября в_18:00'));
  });

  it('относительное время, как на макетах', () => {
    const ago = (ms: number) => new Date(now.getTime() - ms);
    const min = 60_000;
    const day = 24 * 60 * min;
    expect(ru.relative(ago(20_000), now)).toBe('только что');
    expect(ru.relative(ago(15 * min), now)).toBe(nb('15_мин назад'));
    expect(ru.relative(ago(61 * min), now)).toBe(nb('1_ч назад'));
    expect(ru.relative(ago(day), now)).toBe('вчера');
    expect(ru.relative(ago(2 * day), now)).toBe('2 дня назад');
    expect(ru.relative(ago(5 * day), now)).toBe('5 дней назад');
    expect(ru.relative(ago(10 * day), now)).toBe('17 сентября');
    expect(lat.relative(ago(15 * min), now)).toBe(nb('pre 15_min'));
    expect(lat.relative(ago(day), now)).toBe('juče');
    expect(cyr.relative(ago(5 * day), now)).toBe('пре 5 дана');
  });
});

describe('плюралы', () => {
  const reviews = (locale: Locale, count: number) =>
    formatMessage(locale, 'count.reviews', { count });

  it.each([
    [1, '1 отзыв', '1 utisak', '1 утисак'],
    [2, '2 отзыва', '2 utiska', '2 утиска'],
    [5, '5 отзывов', '5 utisaka', '5 утисака'],
    [21, '21 отзыв', '21 utisak', '21 утисак'],
    [37, '37 отзывов', '37 utisaka', '37 утисака'],
    [112, '112 отзывов', '112 utisaka', '112 утисака'],
  ])('%d', (count, ruText, latText, cyrText) => {
    expect(reviews('ru', count)).toBe(ruText);
    expect(reviews('sr-Latn', count)).toBe(latText);
    expect(reviews('sr-Cyrl', count)).toBe(cyrText);
  });

  it('«осталось 2 места»', () => {
    expect(formatMessage('ru', 'count.respondWithSlots', { count: 2 })).toBe(
      'Откликнуться · осталось 2 места',
    );
    expect(formatMessage('ru', 'count.slotsLeft', { count: 1 })).toBe('осталось 1 место');
    expect(formatMessage('ru', 'count.slotsLeft', { count: 5 })).toBe('осталось 5 мест');
    expect(formatMessage('sr-Latn', 'count.slotsLeft', { count: 2 })).toBe('još 2 slobodna mesta');
  });

  it('большие числа в # — с разделителем локали', () => {
    expect(reviews('ru', 1_000)).toBe(nb('1_000 отзывов'));
    expect(reviews('sr-Latn', 1_000)).toBe('1.000 utisaka');
  });
});
