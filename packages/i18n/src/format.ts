// Форматтеры: деньги (para → «5 000 RSD»), цены и бюджет, расстояние, даты в Europe/Belgrade, относительное время.
// Числа — Intl по региону RS/RU; слова — из каталога common, как и весь остальной текст.
import type { BudgetBucket, Para, Price } from '@sosed/domain';
import { CURRENCY, paraToRsd } from '@sosed/domain';
import { IntlMessageFormat } from 'intl-messageformat';

import { flattenCatalog } from './catalog.ts';
import type { Locale } from './locale.ts';
import { DEFAULT_LOCALE, INTL_LOCALE, TIME_ZONE } from './locale.ts';
import type { Messages } from './resources.ts';
import { RESOURCES } from './resources.ts';

/** Неразрывный пробел: между числом и валютой, «≈» и числом. */
export const NBSP = String.fromCharCode(0xa0);

type Leaves<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

export type CommonKey = Leaves<Messages['common']>;

const flat = new Map<Locale, Record<string, string>>();
const compiled = new Map<string, IntlMessageFormat>();

function source(locale: Locale, key: string): string {
  let messages = flat.get(locale);
  if (!messages) {
    messages = flattenCatalog(RESOURCES[locale].common);
    flat.set(locale, messages);
  }
  const message = messages[key];
  if (message !== undefined) return message;
  if (locale === DEFAULT_LOCALE) throw new Error(`Нет сообщения common:${key}`);
  return source(DEFAULT_LOCALE, key);
}

/** ICU-сообщение из common без экземпляра i18next (для форматтеров и тестов). */
export function formatMessage(
  locale: Locale,
  key: CommonKey,
  values?: Record<string, string | number>,
): string {
  const id = `${locale}:${key}`;
  let mf = compiled.get(id);
  if (!mf) {
    mf = new IntlMessageFormat(source(locale, key), INTL_LOCALE[locale]);
    compiled.set(id, mf);
  }
  return String(mf.format(values));
}

const DAY_MS = 86_400_000;

function dayNumber(date: Date): number {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return Date.UTC(get('year'), get('month') - 1, get('day')) / DAY_MS;
}

export interface Format {
  number(value: number, maxFractionDigits?: number): string;
  /** Рейтинг — всегда с одним знаком: «4,9», «5,0» (карточка S05, профиль S08). */
  rating(value: number): string;
  /** para → «5 000 RSD» (ru), «5.000 RSD» (sr). */
  money(amount: Para): string;
  moneyRange(min: Para, max: Para): string;
  price(price: Price): string;
  budgetBucket(bucket: BudgetBucket): string;
  /** Метры → «≈ 600 м», «≈ 1,5 км», «≈ 12 км». */
  distance(meters: number): string;
  time(date: Date): string;
  date(date: Date, now?: Date): string;
  /** Дата с годом всегда: «27 сентября 2026» (редакция документа, S48). */
  fullDate(date: Date): string;
  /** Месяц отзыва: «Сентябрь», «Septembar». */
  month(date: Date): string;
  /** «сегодня в 19:00», «завтра в 10:00», «12 октября в 19:00». */
  calendar(date: Date, now?: Date): string;
  /** «только что», «15 мин назад», «2 ч назад», «вчера», «5 дней назад», дальше — дата. */
  relative(date: Date, now?: Date): string;
}

export function createFormat(locale: Locale): Format {
  const intl = INTL_LOCALE[locale];
  const t = (key: CommonKey, values?: Record<string, string | number>) =>
    formatMessage(locale, key, values);

  const number = (value: number, maxFractionDigits = 0) =>
    new Intl.NumberFormat(intl, { maximumFractionDigits: maxFractionDigits }).format(value);
  const rating = (value: number) =>
    new Intl.NumberFormat(intl, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(
      value,
    );

  const amount = (para: Para) => {
    const rsd = paraToRsd(para);
    return Number.isInteger(rsd)
      ? number(rsd)
      : new Intl.NumberFormat(intl, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
          rsd,
        );
  };
  const money = (para: Para) => `${amount(para)}${NBSP}${CURRENCY}`;
  const moneyRange = (min: Para, max: Para) => `${amount(min)}–${amount(max)}${NBSP}${CURRENCY}`;

  const price = (p: Price): string => {
    if (p.type === 'negotiable') return t('price.negotiable');
    const min = p.min ?? 0;
    let core: string;
    if (p.type === 'from') core = t('price.from', { amount: money(min) });
    else if (p.type === 'range' && p.max == null) core = t('price.from', { amount: money(min) });
    else if (p.type === 'range' && min === 0) core = t('price.upTo', { amount: money(p.max ?? 0) });
    else if (p.type === 'range') core = moneyRange(min, p.max ?? min);
    else core = money(min);
    const unit = p.type === 'hourly' ? 'hour' : (p.unit ?? 'work');
    return t(`price.perUnit.${unit}`, { price: core });
  };

  const thousands = (para: Para) => number(paraToRsd(para) / 1000);
  const budgetBucket = (b: BudgetBucket) => {
    if (b.max === null) return t('budget.over', { min: thousands(b.min) });
    if (b.min === 0) return t('budget.upTo', { max: number(paraToRsd(b.max)) });
    return t('budget.range', { min: thousands(b.min), max: thousands(b.max) });
  };

  const distance = (meters: number) => {
    const rounded = Math.max(100, Math.round(meters / 100) * 100);
    if (rounded < 1000) return t('distance.m', { value: number(rounded) });
    const km = meters / 1000;
    return t('distance.km', { value: number(km, km < 10 ? 1 : 0) });
  };

  const time = (date: Date) =>
    new Intl.DateTimeFormat(intl, {
      timeZone: TIME_ZONE,
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(date);

  const dateOnly = (date: Date, now = new Date()) => {
    const sameYear =
      new Intl.DateTimeFormat('en', { timeZone: TIME_ZONE, year: 'numeric' }).format(date) ===
      new Intl.DateTimeFormat('en', { timeZone: TIME_ZONE, year: 'numeric' }).format(now);
    return new Intl.DateTimeFormat(intl, {
      timeZone: TIME_ZONE,
      day: 'numeric',
      month: 'long',
      ...(sameYear ? {} : { year: 'numeric' }),
    }).format(date);
  };

  // ru Intl дописывает «г.» после года — на макетах его нет («от 26 сентября 2026»)
  const fullDate = (date: Date) =>
    new Intl.DateTimeFormat(intl, {
      timeZone: TIME_ZONE,
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
      .format(date)
      .replace(/\s*г\.$/, '');

  const calendar = (date: Date, now = new Date()) => {
    const diff = dayNumber(date) - dayNumber(now);
    const day =
      diff === 0 ? t('time.today') : diff === 1 ? t('time.tomorrow') : dateOnly(date, now);
    return t('time.dayAt', { day, time: time(date) });
  };

  const relative = (date: Date, now = new Date()) => {
    const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
    if (minutes < 1) return t('time.justNow');
    if (minutes < 60) return t('time.minutesAgo', { count: minutes });
    const days = dayNumber(now) - dayNumber(date);
    if (days === 0) return t('time.hoursAgo', { count: Math.floor(minutes / 60) });
    if (days === 1) return t('time.yesterday');
    if (days < 7) return t('time.daysAgo', { count: days });
    return dateOnly(date, now);
  };

  const month = (date: Date) => {
    const name = new Intl.DateTimeFormat(intl, { timeZone: TIME_ZONE, month: 'long' }).format(date);
    return name.charAt(0).toUpperCase() + name.slice(1);
  };

  return {
    number,
    rating,
    money,
    moneyRange,
    price,
    budgetBucket,
    distance,
    time,
    date: dateOnly,
    fullDate,
    month,
    calendar,
    relative,
  };
}
