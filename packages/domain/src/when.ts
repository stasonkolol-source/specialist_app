// «Когда» заявки на S20b (DEVELOPMENT_PLAN 5.2): выбор человека → срочность и удобное время для
// POST /jobs. Всё — по Белграду (BUSINESS_TIME_ZONE), где бы ни был телефон: как у сервера
// (`lifetime` заявки) и у «доступен сегодня».
import type { JobUrgency } from './job.ts';
import { BUSINESS_TIME_ZONE, businessTime } from './availability.ts';

/** Карточки «Когда» на артборде S20b: срочно, сегодня, на неделе, своя дата. */
export const WHEN_CHOICES = ['asap', 'today', 'week', 'date'] as const;
export type WhenChoice = (typeof WHEN_CHOICES)[number];

/** «Удобное время сегодня»: окна по три часа — как на артборде. */
export const TODAY_SLOTS = [
  [9, 12],
  [12, 15],
  [15, 18],
  [18, 21],
] as const;
export type TodaySlot = (typeof TODAY_SLOTS)[number];

/** Своя дата — не дальше: заявка «не срочно» живёт 30 дней. */
export const MAX_DAYS_AHEAD = 30;
/** На неделе — заявка `this_week` (7 дней); дальше — `flexible`. */
const WEEK_DAYS = 7;

const DAY_MS = 24 * 60 * 60_000;

/** День по Белграду: «2026-10-02». */
export function businessDay(moment: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: BUSINESS_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(moment);
}

/** Сдвиг дня: «2026-10-31» + 1 → «2026-11-01». */
export function addDays(day: string, days: number): string {
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, date) + days * DAY_MS).toISOString().slice(0, 10);
}

/** Момент по белградским дню и часам: «2026-10-02», 18:00 → 16:00 UTC (летнее время). */
export function businessMoment(day: string, hour: number, minute = 0): Date {
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number);
  const wall = Date.UTC(year, month - 1, date, hour, minute);
  // смещение пояса в этот момент; второй проход — на случай перехода на летнее время
  let moment = wall - offsetAt(wall);
  moment = wall - offsetAt(moment);
  return new Date(moment);
}

function offsetAt(moment: number): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: BUSINESS_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(moment));
  const value = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  const wall = Date.UTC(
    value('year'),
    value('month') - 1,
    value('day'),
    value('hour'),
    value('minute'),
  );
  return wall - Math.floor(moment / 60_000) * 60_000;
}

/** Окно ещё не кончилось сегодня: «18–21» можно выбрать до 20:59. */
export function isSlotOpen(slot: TodaySlot, now: Date): boolean {
  return businessTime(now).hour < slot[1];
}

/** Ключ окна для хранения и кнопки: «18-21». */
export const slotKey = (slot: TodaySlot) => `${slot[0]}-${slot[1]}`;

export function slotOf(key: string | null): TodaySlot | null {
  return TODAY_SLOTS.find((slot) => slotKey(slot) === key) ?? null;
}

export interface WhenInput {
  choice: WhenChoice;
  /** «Сегодня»: окно, если выбрано. */
  slot?: TodaySlot | null;
  /** «Дата и время»: день по Белграду и «ЧЧ:ММ». */
  day?: string | null;
  time?: string | null;
}

export interface JobWhen {
  urgency: JobUrgency;
  preferredFrom: Date | null;
  preferredTo: Date | null;
}

/**
 * Срочность и удобное время для сервера. Своя дата: сегодня — `today`, в ближайшую неделю —
 * `this_week`, дальше — `flexible`; время — начало, конца нет. null — выбор неполный.
 */
export function jobWhen(input: WhenInput, now: Date): JobWhen | null {
  const today = businessDay(now);
  switch (input.choice) {
    case 'asap':
      return { urgency: 'asap', preferredFrom: null, preferredTo: null };
    case 'week':
      return { urgency: 'this_week', preferredFrom: null, preferredTo: null };
    case 'today': {
      const slot = input.slot ?? null;
      if (!slot) return { urgency: 'today', preferredFrom: null, preferredTo: null };
      return {
        urgency: 'today',
        preferredFrom: businessMoment(today, slot[0]),
        preferredTo: businessMoment(today, slot[1]),
      };
    }
    case 'date': {
      const { day, time } = input;
      const match = /^(\d{2}):(\d{2})$/.exec(time ?? '');
      if (!day || !match || day < today || day > addDays(today, MAX_DAYS_AHEAD)) return null;
      const from = businessMoment(day, Number(match[1]), Number(match[2]));
      if (from <= now) return null;
      const urgency: JobUrgency =
        day === today ? 'today' : day < addDays(today, WEEK_DAYS) ? 'this_week' : 'flexible';
      return { urgency, preferredFrom: from, preferredTo: null };
    }
  }
}
