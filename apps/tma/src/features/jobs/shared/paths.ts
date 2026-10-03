// Адреса вкладки «Заявки»: лента S13 и сегменты «Мои отклики» (5.5) и «Мои заявки» (5.6), заявка
// S15 (DEVELOPMENT_PLAN 5.3), отклик на неё S16 и шаблоны откликов S57 (5.5); мастер «Создать
// заявку» S20a–d и итог S21 (5.2). Вход в мастер —
// «Создать заявку» таббара, CTA Главной и пустой выдачи, «Заказать эту услугу» на S09: они
// передают категорию и название (`?category=&title=`) — новый черновик начинается с них.
import type { ResponseGroup } from '@sosed/api-client';
import { isUuid } from '@sosed/links';

/** Сегменты вкладки: у каждого свой адрес — таббар виден на всех трёх (AppShell). */
export const JOBS_PATHS = {
  feed: '/jobs',
  responses: '/jobs/responses',
  mine: '/jobs/mine',
  job: '/jobs/$jobId',
  respond: '/jobs/$jobId/respond',
  templates: '/jobs/responses/templates',
  manage: '/jobs/$jobId/manage',
  response: '/jobs/$jobId/responses/$responseId',
  deal: '/deals/$dealId',
  review: '/deals/$dealId/review',
  history: '/deals',
} as const;

export type JobsSegment = Exclude<
  keyof typeof JOBS_PATHS,
  'job' | 'respond' | 'templates' | 'manage' | 'response' | 'deal' | 'review' | 'history'
>;
export const JOBS_SEGMENTS: readonly JobsSegment[] = ['feed', 'responses', 'mine'];

/** Избранное S12: «Мастера» — фича catalog, «Задачи» — сохранённые заявки (здесь). */
export const SAVED_PATHS = { masters: '/favorites', jobs: '/favorites/jobs' } as const;
export type SavedSegment = keyof typeof SAVED_PATHS;

/** Профиль S31 (фича account): «Назад» из S12 без истории. */
export const ACCOUNT_PATH = '/profile';

/** Заявка S15: deep link `j_` (routes/startapp.ts) ведёт сюда же. */
export const jobPath = (jobId: string) => `/jobs/${jobId}`;

/** Отклик S16 на заявку; свой отклик там же правится. */
export const respondPath = (jobId: string) => `/jobs/${jobId}/respond`;

/** Своя заявка S23 (5.6): статус, отклики, закрыть, продлить, пригласить. */
export const managePath = (jobId: string) => `/jobs/${jobId}/manage`;

/** Отклик на свою заявку глазами клиента S24 (6.2): выбрать, отклонить. */
export const choicePath = (jobId: string, responseId: string) =>
  `/jobs/${jobId}/responses/${responseId}`;

/** Сделка S26 (6.2): из S25, «Открыть сделку» S23 и S17, уведомлений бота (`d_`). */
export const dealPath = (dealId: string) => `/deals/${dealId}`;

export interface HistorySearch {
  /** Вкладка «Отзывы» S28: ссылка `m_reviews` из уведомления о новом отзыве. */
  tab?: 'reviews';
}

export function historySearch(search: Record<string, unknown>): HistorySearch {
  return search.tab === 'reviews' ? { tab: 'reviews' } : {};
}

/** Отзыв S27 (7.3): из S26 и S28 («Оставить отзыв»), из бота — через сделку (`d_`). */
export const reviewPath = (dealId: string) => `/deals/${dealId}/review`;

/** Диалог S30 (фича messages, 6.4): «Написать» на S24 открывает диалог по отклику. */
export const chatPath = (conversationId: string) => `/messages/${conversationId}`;

/** Профиль специалиста S08 (фича catalog): из мини-профиля S24 и S26. */
export const specialistPath = (profileId: string) => `/specialists/${profileId}`;

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

export interface EditSearch {
  /** Мастер правит свою заявку (S23 «Изменить», 5.6), а не новую. */
  edit?: string;
}

export interface CreateSearch extends EditSearch {
  category?: number;
  title?: string;
  /** Прямой запрос этому профилю (S08, S09; 5.6): заявку увидит только этот профиль. */
  direct?: string;
}

/** validateSearch шагов мастера: правится ли своя заявка — её id. */
export function editSearch(search: Record<string, unknown>): EditSearch {
  return typeof search.edit === 'string' && isUuid(search.edit) ? { edit: search.edit } : {};
}

/** validateSearch первого шага: категория — целое больше нуля, название — строка. */
export function createSearch(search: Record<string, unknown>): CreateSearch {
  const result: CreateSearch = editSearch(search);
  const category = Number(search.category);
  if (Number.isInteger(category) && category > 0) result.category = category;
  if (typeof search.title === 'string' && search.title.trim()) {
    result.title = search.title.trim().slice(0, MAX_PREFILL_TITLE);
  }
  if (typeof search.direct === 'string' && isUuid(search.direct)) result.direct = search.direct;
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

export interface ResponsesSearch {
  /** Чип S17; без него — «Все». */
  status?: ResponseGroup;
  /** Отклик только что отправлен с S16: «клиент увидит его после проверки». */
  sent?: boolean;
}

const GROUPS: readonly ResponseGroup[] = ['active', 'accepted', 'not_selected', 'archive'];

/** validateSearch S17: чип — из известных, `sent` — только «да». */
export function responsesSearch(search: Record<string, unknown>): ResponsesSearch {
  const result: ResponsesSearch = {};
  const status = GROUPS.find((group) => group === search.status);
  if (status) result.status = status;
  if (search.sent === true || search.sent === 'true' || search.sent === 1) result.sent = true;
  return result;
}

/** Id заявки из адреса: `/jobs/oops` — не заявка, запрашивать нечего. */
export const jobIdOf = (value: string): string | null => (isUuid(value) ? value : null);
