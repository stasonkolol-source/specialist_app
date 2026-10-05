// Форматтеры: деньги (para → «5 000 RSD»), цены и бюджет, расстояние, даты в Europe/Belgrade, относительное время.
// Числа — Intl по региону RS/RU; слова — из каталога common, как и весь остальной текст.
import type { BudgetBucket, Para, Price } from '@sosed/domain';
import { CURRENCY, paraToRsd } from '@sosed/domain';
import { IntlMessageFormat } from 'intl-messageformat';

import { flattenCatalog } from './catalog.ts';
import type { Locale } from './locale.ts';
import { DEFAULT_LOCALE, INTL_LOCALE, TIME_ZONE } from './locale.ts';
import type { Messages } from './resources.ts';
import { commonOf } from './resources.ts';

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
    messages = flattenCatalog(commonOf(locale));
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

// Intl-форматтеры дорогие в создании, а карточки выдачи, ленты и чата форматируют сотни чисел и
// дат за отрисовку: один форматтер на язык и набор опций на всё приложение. Наборов опций —
// десяток, кэш не растёт.
const numberFormats = new Map<string, Intl.NumberFormat>();
const dateFormats = new Map<string, Intl.DateTimeFormat>();

function numberFormat(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat(locale, options);
    numberFormats.set(key, format);
  }
  return format;
}

function dateFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let format = dateFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, options);
    dateFormats.set(key, format);
  }
  return format;
}

const DAY_MS = 86_400_000;

function dayNumber(date: Date): number {
  const parts = dateFormat('en-CA', {
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
  /** Дата после предлога или в значении «когда»: «до 3 октября», «закрыта 3 октября»;
   *  «do 3. oktobra», «zatvoren 3. oktobra» (S49b, S26, S22, S31, S45). Подпись — `date`. */
  dateGenitive(date: Date, now?: Date): string;
  /** Дата с годом всегда: «27 сентября 2026». */
  fullDate(date: Date): string;
  /** Дата с годом после предлога: «от 27 сентября 2026», «od 27. septembra 2026.» (S48). */
  fullDateGenitive(date: Date): string;
  /** Месяц отзыва: «Сентябрь», «Septembar»; не этого года — с годом: «Октябрь 2025»,
   *  «Oktobar 2025.». */
  month(date: Date, now?: Date): string;
  /** «сегодня в 19:00», «завтра в 10:00», «12 октября в 19:00». */
  calendar(date: Date, now?: Date): string;
  /** То же после предлога или глагола: «до 12 октября в 19:00», «do 12. oktobra u 19:00»,
   *  «poslato 3. oktobra u 10:00» (S26, S52, S53, S18). */
  calendarGenitive(date: Date, now?: Date): string;
  /** «только что», «15 мин назад», «2 ч назад», «вчера», «5 дней назад», дальше — дата. */
  relative(date: Date, now?: Date): string;
  /** То же после глагола: «отправлена 3 октября», «poslat 3. oktobra» (S23, S55). */
  relativeGenitive(date: Date, now?: Date): string;
}

/** Сербский месяц в родительном падеже: «septembar» → «septembra», «mart» → «marta» (и кириллицей).
 *  У Intl (CLDR) сербские месяцы — в именительном; если когда-нибудь придёт родительный (на «-a»),
 *  он остаётся как есть. */
function serbianGenitive(month: string): string {
  if (/[aа]$/.test(month)) return month;
  const cyrillic = /[\u0400-\u04ff]/.test(month);
  // беглое «а»: septembar → septembra, октобар → октобра
  if (/(bar|бар)$/.test(month)) return `${month.slice(0, -2)}${cyrillic ? 'ра' : 'ra'}`;
  return `${month}${cyrillic ? 'а' : 'a'}`;
}

const formats = new Map<Locale, Format>();

/** Форматтеры языка — один набор на язык: useFormat в каждой карточке получает тот же. */
export function createFormat(locale: Locale): Format {
  let format = formats.get(locale);
  if (!format) {
    format = buildFormat(locale);
    formats.set(locale, format);
  }
  return format;
}

function buildFormat(locale: Locale): Format {
  const intl = INTL_LOCALE[locale];
  const t = (key: CommonKey, values?: Record<string, string | number>) =>
    formatMessage(locale, key, values);

  const number = (value: number, maxFractionDigits = 0) =>
    numberFormat(intl, { maximumFractionDigits: maxFractionDigits }).format(value);
  const rating = (value: number) =>
    numberFormat(intl, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);

  const amount = (para: Para) => {
    const rsd = paraToRsd(para);
    return Number.isInteger(rsd)
      ? number(rsd)
      : numberFormat(intl, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rsd);
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
    dateFormat(intl, {
      timeZone: TIME_ZONE,
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(date);

  // После предлога («до», «от»; «do», «od») и в значении «когда» после глагола («zatvoren 3.
  // oktobra») месяц — в родительном падеже. Русский Intl так и пишет («3 октября»), сербский — в
  // именительном («do 3. oktobar»): склоняем сами. Именительный — только у подписей: день над
  // перепиской, дата в строке «· …».
  const formatDate = (formatter: Intl.DateTimeFormat, date: Date, genitive: boolean) =>
    genitive && locale !== 'ru'
      ? formatter
          .formatToParts(date)
          .map((part) => (part.type === 'month' ? serbianGenitive(part.value) : part.value))
          .join('')
      : formatter.format(date);

  const dateOnly = (date: Date, now = new Date(), genitive = false) => {
    const year = dateFormat('en', { timeZone: TIME_ZONE, year: 'numeric' });
    const sameYear = year.format(date) === year.format(now);
    const formatter = dateFormat(intl, {
      timeZone: TIME_ZONE,
      day: 'numeric',
      month: 'long',
      ...(sameYear ? {} : { year: 'numeric' }),
    });
    return formatDate(formatter, date, genitive);
  };

  // ru Intl дописывает «г.» после года — на макетах его нет («от 26 сентября 2026»)
  const fullDate = (date: Date, genitive = false) =>
    formatDate(
      dateFormat(intl, { timeZone: TIME_ZONE, day: 'numeric', month: 'long', year: 'numeric' }),
      date,
      genitive,
    ).replace(/\s*г\.$/, '');

  const calendar = (date: Date, now = new Date(), genitive = false) => {
    const diff = dayNumber(date) - dayNumber(now);
    const day =
      diff === 0
        ? t('time.today')
        : diff === 1
          ? t('time.tomorrow')
          : dateOnly(date, now, genitive);
    return t('time.dayAt', { day, time: time(date) });
  };

  const relative = (date: Date, now = new Date(), genitive = false) => {
    const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
    if (minutes < 1) return t('time.justNow');
    if (minutes < 60) return t('time.minutesAgo', { count: minutes });
    const days = dayNumber(now) - dayNumber(date);
    if (days === 0) return t('time.hoursAgo', { count: Math.floor(minutes / 60) });
    if (days === 1) return t('time.yesterday');
    if (days < 7) return t('time.daysAgo', { count: days });
    return dateOnly(date, now, genitive);
  };

  // Отзыв прошлого года без года читался как этот месяц или будущий: «Октябрь» в октябре 2026 про
  // октябрь 2025 (SMOKE-1). ru Intl дописывает «г.» — убираем, как у fullDate
  const month = (date: Date, now = new Date()) => {
    const year = dateFormat('en', { timeZone: TIME_ZONE, year: 'numeric' });
    const sameYear = year.format(date) === year.format(now);
    const name = dateFormat(intl, {
      timeZone: TIME_ZONE,
      month: 'long',
      ...(sameYear ? {} : { year: 'numeric' }),
    })
      .format(date)
      .replace(/\s*г\.$/, '');
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
    date: (date, now) => dateOnly(date, now),
    dateGenitive: (date, now) => dateOnly(date, now, true),
    fullDate: (date) => fullDate(date),
    fullDateGenitive: (date) => fullDate(date, true),
    month,
    calendar: (date, now) => calendar(date, now),
    calendarGenitive: (date, now) => calendar(date, now, true),
    relative: (date, now) => relative(date, now),
    relativeGenitive: (date, now) => relative(date, now, true),
  };
}
