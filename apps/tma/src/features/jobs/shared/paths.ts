// Адреса вкладки «Заявки»: лента S13 и сегменты «Мои отклики» (5.5) и «Мои заявки» (5.6), заявка
// S15 (DEVELOPMENT_PLAN 5.3); мастер «Создать заявку» S20a–d и итог S21 (5.2). Вход в мастер —
// «Создать заявку» таббара, CTA Главной и пустой выдачи, «Заказать эту услугу» на S09: они
// передают категорию и название (`?category=&title=`) — новый черновик начинается с них.
import { isUuid } from '@sosed/links';

/** Сегменты вкладки: у каждого свой адрес — таббар виден на всех трёх (AppShell). */
export const JOBS_PATHS = {
  feed: '/jobs',
  responses: '/jobs/responses',
  mine: '/jobs/mine',
  job: '/jobs/$jobId',
} as const;

export type JobsSegment = Exclude<keyof typeof JOBS_PATHS, 'job'>;
export const JOBS_SEGMENTS: readonly JobsSegment[] = ['feed', 'responses', 'mine'];

/** Избранное S12: «Мастера» — фича catalog, «Задачи» — сохранённые заявки (здесь). */
export const SAVED_PATHS = { masters: '/favorites', jobs: '/favorites/jobs' } as const;
export type SavedSegment = keyof typeof SAVED_PATHS;

/** Профиль S31 (фича account): «Назад» из S12 без истории. */
export const ACCOUNT_PATH = '/profile';

/** Заявка S15: deep link `j_` (routes/startapp.ts) ведёт сюда же. */
export const jobPath = (jobId: string) => `/jobs/${jobId}`;

export const CREATE_PATHS = {
  what: '/jobs/new',
  when: '/jobs/new/when',
  budget: '/jobs/new/budget',
  preview: '/jobs/new/preview',
  done: '/jobs/new/done',
} as const;

export type CreateStep = Exclude<keyof typeof CREATE_PATHS, 'done'>;
export const CREATE_STEPS: readonly CreateStep[] = ['what', 'when', 'budget', 'preview'];

/** Главная: сюда — «Готово» на S21 и «Назад» с первого шага без истории. */
export const HOME_PATH = '/';

/** Название из CTA — не длиннее заголовка заявки. */
const MAX_PREFILL_TITLE = 120;

export interface CreateSearch {
  category?: number;
  title?: string;
}

/** validateSearch первого шага: категория — целое больше нуля, название — строка. */
export function createSearch(search: Record<string, unknown>): CreateSearch {
  const result: CreateSearch = {};
  const category = Number(search.category);
  if (Number.isInteger(category) && category > 0) result.category = category;
  if (typeof search.title === 'string' && search.title.trim()) {
    result.title = search.title.trim().slice(0, MAX_PREFILL_TITLE);
  }
  return result;
}

export interface DoneSearch {
  job?: string;
}

/** validateSearch S21: id опубликованной заявки. */
export function doneSearch(search: Record<string, unknown>): DoneSearch {
  return typeof search.job === 'string' && search.job ? { job: search.job } : {};
}

const COORDINATE_DIGITS = 3;

export interface JobSearch {
  /** Точка ленты, из которой открыли заявку: «≈ 1,2 км от вас». */
  lat?: number;
  lon?: number;
}

function coordinate(value: unknown, limit: number): number | undefined {
  const number = typeof value === 'string' ? Number(value) : value;
  if (typeof number !== 'number' || !Number.isFinite(number) || Math.abs(number) > limit) {
    return undefined;
  }
  return Number(number.toFixed(COORDINATE_DIGITS));
}

/** validateSearch S15: точка — только парой. */
export function jobSearch(search: Record<string, unknown>): JobSearch {
  const lat = coordinate(search.lat, 90);
  const lon = coordinate(search.lon, 180);
  return lat !== undefined && lon !== undefined ? { lat, lon } : {};
}

/** Id заявки из адреса: `/jobs/oops` — не заявка, запрашивать нечего. */
export const jobIdOf = (value: string): string | null => (isUuid(value) ? value : null);
