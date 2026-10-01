// «Доступен сегодня до …» (S33, S38; DEVELOPMENT_PLAN 2.10): варианты по артборду и «сегодня» по
// Белграду — бизнес-день площадки, как BUSINESS_TZ у сервера.

/** Часовой пояс площадки: «сегодня» и «до 20:00» — по нему, где бы ни был телефон. */
export const BUSINESS_TIME_ZONE = 'Europe/Belgrade';

/** Варианты S38: «до 18:00», «до 20:00», «до 22:00». */
export const AVAILABILITY_HOURS = [18, 20, 22] as const;
export type AvailabilityHour = (typeof AVAILABILITY_HOURS)[number];

/** По умолчанию — «до 20:00», как на артбордах S33 и S38. */
const DEFAULT_HOUR: AvailabilityHour = 20;

/** Часы и минуты момента по Белграду. */
export function businessTime(moment: Date): { hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: BUSINESS_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(moment);
  const value = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  return { hour: value('hour'), minute: value('minute') };
}

/** Вариант ещё впереди сегодня: «до 20:00» можно включить до 19:59. */
export function isUpcoming(hour: number, now: Date): boolean {
  return businessTime(now).hour < hour;
}

/** Быстрое включение на S33: «до 20:00», а если поздно — ближайший; null — сегодня уже всё. */
export function quickHour(now: Date): AvailabilityHour | null {
  if (isUpcoming(DEFAULT_HOUR, now)) return DEFAULT_HOUR;
  return AVAILABILITY_HOURS.find((hour) => isUpcoming(hour, now)) ?? null;
}

/** До какого момента доступен; null — выключено или срок уже вышел (сервер снимет сам). */
export function availableUntil(availableUntil: string | null, now: Date): Date | null {
  if (!availableUntil) return null;
  const until = new Date(availableUntil);
  return until > now ? until : null;
}

/** Вариант, совпадающий со сроком («до 20:00» → 20); иначе (свой срок из бота) — null. */
export function availabilityHour(until: Date | null): AvailabilityHour | null {
  if (!until) return null;
  const { hour, minute } = businessTime(until);
  return minute === 0 ? (AVAILABILITY_HOURS.find((known) => known === hour) ?? null) : null;
}

/** «HH:00» варианта — тело PUT /me/profile/availability. */
export const untilTime = (hour: AvailabilityHour) => `${String(hour).padStart(2, '0')}:00`;
