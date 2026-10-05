// Даты переписки. В ленте S30 у сообщений только время — день подписывает плашка над первым
// сообщением дня: «Сегодня», «Вчера», «2 октября». В строке списка S29 время короткое, как в
// Telegram: «16:05» сегодня, «вчера», день недели «пт» за последнюю неделю, раньше — «2 окт».
// Календарные дни — по Белграду, как у остальных дат (`TIME_ZONE`); слова — из common, форматы
// — Intl языка интерфейса. Не в @sosed/i18n: форматтеры там — в первом экране (бюджет 200 KB).
import type { Locale } from '@sosed/i18n';
import { INTL_LOCALE, TIME_ZONE, useFormat, useLocale, useTranslation } from '@sosed/i18n';

const DAY_MS = 86_400_000;
const WEEK_DAYS = 7;

const calendarDay = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** День по Белграду: «2026-10-02» — ключ дня и `dateTime` подписи. */
export function dayKey(date: Date): string {
  return calendarDay.format(date);
}

/** Сколько календарных дней от `date` до `now`: вчера — 1. */
export function daysBefore(date: Date, now: Date): number {
  return Math.round((Date.parse(dayKey(now)) - Date.parse(dayKey(date))) / DAY_MS);
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
// «окт.», «2.10.25.» — без точки в конце: в строке списка она лишняя, как на артборде S29
const trimDot = (text: string) => text.replace(/\.$/, '');

const shortFormats = new Map<string, Intl.DateTimeFormat>();

function short(locale: Locale, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let format = shortFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(INTL_LOCALE[locale], { timeZone: TIME_ZONE, ...options });
    shortFormats.set(key, format);
  }
  return format;
}

/** Подпись дня в ленте: «Сегодня», «Вчера», «2 октября» (другой год — с годом). */
export function useDayLabel(): (date: Date, now?: Date) => string {
  const { t } = useTranslation();
  const format = useFormat();
  return (date, now = new Date()) => {
    const days = daysBefore(date, now);
    if (days === 0) return capitalize(t('time.today'));
    if (days === 1) return capitalize(t('time.yesterday'));
    return format.date(date, now);
  };
}

/** Время строки списка: «16:05», «вчера», «пт», «2 окт», другой год — «02.10.25». */
export function useListTime(): (date: Date, now?: Date) => string {
  const { t } = useTranslation();
  const format = useFormat();
  const locale = useLocale();
  return (date, now = new Date()) => {
    const days = daysBefore(date, now);
    // часы устройства могут отставать от сервера: «из будущего» — тоже сегодня
    if (days <= 0) return format.time(date);
    if (days === 1) return t('time.yesterday');
    if (days < WEEK_DAYS) return short(locale, { weekday: 'short' }).format(date);
    const sameYear = dayKey(date).slice(0, 4) === dayKey(now).slice(0, 4);
    return trimDot(
      short(
        locale,
        sameYear
          ? { day: 'numeric', month: 'short' }
          : { day: '2-digit', month: '2-digit', year: '2-digit' },
      ).format(date),
    );
  };
}
