// Адреса мастера «Создать заявку» S20a–d и итога S21 (DEVELOPMENT_PLAN 5.2). Вход — «Создать
// заявку» таббара, CTA Главной и пустой выдачи, «Заказать эту услугу» на S09: они передают
// категорию и название (`?category=&title=`) — новый черновик начинается с них.
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
