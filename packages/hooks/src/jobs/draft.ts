// Черновик заявки S20a–d (DEVELOPMENT_PLAN 5.2): живёт только на клиенте — в DeviceStorage
// Telegram (в браузере — localStorage, так даёт платформа) — и уходит на сервер целиком с S20d
// (POST /jobs без отдельного submit, ARCHITECTURE §8.5). Ключ идемпотентности — один на черновик:
// повторное «Опубликовать» (двойное нажатие, ответ потерялся в сети) не создаёт вторую заявку.
import type { BudgetType, JobIn, JobOut, Language } from '@sosed/api-client';
import type { TodaySlot, WhenChoice } from '@sosed/domain';
import {
  TODAY_SLOTS,
  WHEN_CHOICES,
  businessDay,
  businessTime,
  jobWhen,
  paraToRsd,
  rsdToPara,
  slotKey,
  slotOf,
} from '@sosed/domain';

/** Ключ в хранилище платформы. */
export const DRAFT_STORAGE_KEY = 'job-draft';
const DRAFT_VERSION = 1;
/** Черновик старше недели не продолжаем: задача, скорее всего, уже неактуальна. */
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60_000;

/** Как у сервера (jobs/domain/job.py). */
export const JOB_TITLE_MIN = 5;
export const JOB_TITLE_MAX = 120;
export const JOB_DESCRIPTION_MAX = 3000;
export const JOB_ADDRESS_MAX = 300;
export const JOB_PHOTOS_MAX = 6;
/** Сумма — до 999 999 999 RSD (MAX_BUDGET сервера — миллиард). */
export const BUDGET_DIGITS = 9;

/** Единицы бюджета на артборде S20c: за работу, за час, за визит. */
export const DRAFT_UNITS = ['work', 'hour', 'visit'] as const;
export type DraftUnit = (typeof DRAFT_UNITS)[number];
/** Языки общения на S20c. */
export const DRAFT_LANGUAGES = ['ru', 'sr', 'en'] as const satisfies readonly Language[];
export type DraftLanguage = (typeof DRAFT_LANGUAGES)[number];

/** Прямой запрос (S08 «Написать», S09 «Заказать эту услугу»; 5.6): заявку увидит только этот
 *  специалист. */
export interface DirectTarget {
  profileId: string;
  name: string;
}

export interface DraftPhoto {
  id: string;
  /** Адрес превью для плитки; null — показать нечего. */
  thumb: string | null;
}

export interface JobDraft {
  version: typeof DRAFT_VERSION;
  /** Idempotency-Key публикации: один на черновик. */
  key: string;
  title: string;
  description: string;
  categoryId: number | null;
  /** Название категории — для чипа, пока справочник не загружен. */
  categoryName: string | null;
  /** Категорию подобрали по тексту (`/suggest`) или выбрал человек — подсказка под чипом. */
  categoryChosen: boolean;
  photos: DraftPhoto[];
  when: WhenChoice | null;
  /** «Сегодня»: окно «18-21». */
  slot: string | null;
  /** «Дата и время»: день по Белграду «2026-10-03» и «10:00». */
  day: string | null;
  time: string | null;
  cityId: number | null;
  districtId: number | null;
  address: string;
  budgetType: BudgetType;
  /** Суммы в динарах — цифры, как введены. */
  budgetMin: string;
  budgetMax: string;
  budgetUnit: DraftUnit;
  languages: DraftLanguage[];
  /** Прямой запрос специалисту; нет — заявка для всех исполнителей. */
  direct?: DirectTarget | null;
  /** Когда черновик последний раз меняли (ISO) — для срока жизни. */
  savedAt: string;
}

export function newDraft(key: string, now: Date, languages: DraftLanguage[] = []): JobDraft {
  return {
    version: DRAFT_VERSION,
    key,
    title: '',
    description: '',
    categoryId: null,
    categoryName: null,
    categoryChosen: false,
    photos: [],
    when: null,
    slot: null,
    day: null,
    time: null,
    cityId: null,
    districtId: null,
    address: '',
    budgetType: 'fixed',
    budgetMin: '',
    budgetMax: '',
    budgetUnit: 'work',
    languages,
    savedAt: now.toISOString(),
  };
}

/** Черновик из хранилища; null — его нет, он другой версии, испорчен или устарел. */
export function parseDraft(raw: string | null, now: Date): JobDraft | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isDraft(value)) return null;
  const saved = Date.parse(value.savedAt);
  if (Number.isNaN(saved) || now.getTime() - saved > DRAFT_TTL_MS) return null;
  return value;
}

function isDraft(value: unknown): value is JobDraft {
  if (typeof value !== 'object' || value === null) return false;
  const draft = value as Partial<JobDraft>;
  return (
    draft.version === DRAFT_VERSION &&
    typeof draft.key === 'string' &&
    typeof draft.title === 'string' &&
    typeof draft.description === 'string' &&
    Array.isArray(draft.photos) &&
    Array.isArray(draft.languages) &&
    typeof draft.savedAt === 'string' &&
    (draft.when === null || (WHEN_CHOICES as readonly unknown[]).includes(draft.when))
  );
}

/** Что мешает перейти дальше — коды для подписи под полем. */
export type DraftProblem = 'title' | 'category' | 'when' | 'date' | 'district' | 'amount' | 'range';

/** S20a: заголовок не короче пяти символов и категория. */
export function whatProblems(draft: JobDraft): DraftProblem[] {
  const problems: DraftProblem[] = [];
  if (draft.title.trim().length < JOB_TITLE_MIN) problems.push('title');
  if (draft.categoryId === null) problems.push('category');
  return problems;
}

/** S20b: когда (своя дата — день и время впереди) и район. */
export function whenProblems(draft: JobDraft, now: Date): DraftProblem[] {
  const problems: DraftProblem[] = [];
  if (draft.when === null) problems.push('when');
  else if (draft.when === 'date' && !whenOf(draft, now)) problems.push('date');
  if (draft.districtId === null) problems.push('district');
  return problems;
}

/** S20c: сумма у фикса и «от» у диапазона; «до» больше «от». */
export function budgetProblems(draft: JobDraft): DraftProblem[] {
  if (draft.budgetType === 'negotiable') return [];
  const min = amountOf(draft.budgetMin);
  if (min === null) return ['amount'];
  if (draft.budgetType === 'range') {
    const max = amountOf(draft.budgetMax);
    if (max !== null && max <= min) return ['range'];
  }
  return [];
}

/** Сумма в динарах из ввода; пусто или ноль — null. */
export function amountOf(digits: string): number | null {
  const value = Number(digits.replace(/\D/g, ''));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function whenOf(draft: JobDraft, now: Date) {
  if (draft.when === null) return null;
  const slot: TodaySlot | null = slotOf(draft.slot);
  return jobWhen({ choice: draft.when, slot, day: draft.day, time: draft.time }, now);
}

/** Окно «Сегодня», если выбрано, — для превью S20d «Сегодня 18–21». */
export function draftSlot(draft: JobDraft): TodaySlot | null {
  return draft.when === 'today' ? slotOf(draft.slot) : null;
}

/** Тело POST /jobs; null — черновик ещё не готов (не пройдены шаги). */
export function jobInOf(draft: JobDraft, now: Date): JobIn | null {
  const when = whenOf(draft, now);
  if (
    whatProblems(draft).length > 0 ||
    whenProblems(draft, now).length > 0 ||
    budgetProblems(draft).length > 0 ||
    when === null ||
    draft.categoryId === null ||
    draft.cityId === null
  ) {
    return null;
  }
  const min = amountOf(draft.budgetMin);
  const max = draft.budgetType === 'range' ? amountOf(draft.budgetMax) : null;
  const negotiable = draft.budgetType === 'negotiable';
  const address = draft.address.trim();
  return {
    title: draft.title.trim(),
    description: draft.description.trim(),
    category_id: draft.categoryId,
    urgency: when.urgency,
    preferred_from: when.preferredFrom?.toISOString() ?? null,
    preferred_to: when.preferredTo?.toISOString() ?? null,
    budget_type: draft.budgetType,
    budget_min: negotiable || min === null ? null : rsdToPara(min),
    budget_max: negotiable || max === null ? null : rsdToPara(max),
    budget_unit: draft.budgetUnit,
    city_id: draft.cityId,
    district_id: draft.districtId,
    address_private: address || null,
    languages: [...draft.languages],
    media_ids: draft.photos.map((photo) => photo.id),
  };
}

/** «18:00» по Белграду. */
function clock(moment: Date): string {
  const { hour, minute } = businessTime(moment);
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

const digitsOf = (para: number | undefined) => (para === undefined ? '' : String(paraToRsd(para)));

/** Выбор «когда» мастера из срочности и удобного времени заявки (обратное `jobWhen`). */
function whenOfJob(job: JobOut): Pick<JobDraft, 'when' | 'slot' | 'day' | 'time'> {
  const none = { slot: null, day: null, time: null };
  if (job.urgency === 'asap') return { when: 'asap', ...none };
  const from = job.preferred_from ? new Date(job.preferred_from) : null;
  const to = job.preferred_to ? new Date(job.preferred_to) : null;
  if (from && to && job.urgency === 'today') {
    const slot = TODAY_SLOTS.find(
      ([start, end]) =>
        clock(from) === `${String(start).padStart(2, '0')}:00` &&
        clock(to) === `${String(end).padStart(2, '0')}:00`,
    );
    if (slot) return { when: 'today', ...none, slot: slotKey(slot) };
  }
  if (from) return { when: 'date', slot: null, day: businessDay(from), time: clock(from) };
  return { when: job.urgency === 'today' ? 'today' : 'week', ...none };
}

/**
 * Черновик правки своей заявки (S23 «Изменить», 5.6): мастер S20a–d с её полями. Ключ — id
 * заявки (правке ключ идемпотентности не нужен: её защищает If-Match). Своя дата в прошлом
 * мастер попросит выбрать заново.
 */
export function draftOfJob(job: JobOut, now: Date): JobDraft {
  const units: readonly string[] = DRAFT_UNITS;
  const languages: readonly string[] = DRAFT_LANGUAGES;
  const paired = job.photos.length === job.media_ids.length;
  return {
    version: DRAFT_VERSION,
    key: job.id,
    title: job.title,
    description: job.description,
    categoryId: job.category_id,
    categoryName: null,
    categoryChosen: true,
    photos: job.media_ids.map((id, index) => ({
      id,
      thumb: paired ? (job.photos[index]?.url ?? null) : null,
    })),
    ...whenOfJob(job),
    cityId: job.city_id,
    districtId: job.district_id,
    address: job.address_private ?? '',
    budgetType: job.budget_type,
    budgetMin: digitsOf(job.budget_min?.amount),
    budgetMax: digitsOf(job.budget_max?.amount),
    budgetUnit: units.includes(job.budget_unit) ? (job.budget_unit as DraftUnit) : 'work',
    languages: job.languages.filter((code): code is DraftLanguage => languages.includes(code)),
    savedAt: now.toISOString(),
  };
}
