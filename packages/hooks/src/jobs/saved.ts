// Сохранённые заявки (DEVELOPMENT_PLAN 5.3): сегмент «Задачи» S12 и сердечко на S15 — из одного
// списка GET /me/favorites/jobs, поэтому экраны не расходятся. Нажатие сразу меняет список
// (оптимистично), ошибка возвращает как было, после ответа список перечитывается. Гостю
// сохранённых нет: без сессии запроса нет.
import type { JobCardOut, JobOut, SavedJobsOut } from '@sosed/api-client';
import {
  getJobsListSavedJobsQueryKey,
  getSession,
  jobsListSavedJobs,
  jobsSaveJob,
  jobsUnsaveJob,
} from '@sosed/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { OWN_STALE_MS } from '../cache.ts';

/** Превью фото в карточке — как в ленте. */
const CARD_PHOTOS = 3;

export const savedJobsQueryKey = () => getJobsListSavedJobsQueryKey();

export function useSavedJobs() {
  return useQuery({
    queryKey: savedJobsQueryKey(),
    queryFn: ({ signal }) => jobsListSavedJobs({ signal }),
    enabled: getSession() !== null,
    staleTime: OWN_STALE_MS,
  });
}

/** id сохранённых заявок — для сердечка S15. */
export function savedJobIds(out: SavedJobsOut | undefined): ReadonlySet<string> {
  return new Set(out?.items.map((item) => item.id) ?? []);
}

export interface SavedJobToggle {
  /** Карточка — встать в начало списка S12 до ответа сервера. */
  card: JobCardOut;
  on: boolean;
}

export function useToggleSavedJob() {
  const client = useQueryClient();
  const key = savedJobsQueryKey();
  return useMutation({
    mutationFn: ({ card, on }: SavedJobToggle) =>
      on ? jobsSaveJob(card.id) : jobsUnsaveJob(card.id),
    onMutate: async ({ card, on }) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<SavedJobsOut>(key);
      client.setQueryData<SavedJobsOut>(key, (old) => {
        const items = (old?.items ?? []).filter((item) => item.id !== card.id);
        return { items: on ? [card, ...items] : items };
      });
      return { before };
    },
    onError: (_error, { card }, context) => {
      if (!context) return;
      client.setQueryData<SavedJobsOut>(key, (old) => {
        if (!old) return old;
        // Откатываем только эту карточку: соседние сохранения могли уже завершиться.
        const items = old.items.filter((item) => item.id !== card.id);
        const index = context.before?.items.findIndex((item) => item.id === card.id) ?? -1;
        const previous = context.before?.items[index];
        if (previous) items.splice(index, 0, previous);
        return { items };
      });
    },
    // список уже поправлен оптимистично: сверка с сервером — в фоне
    onSettled: () => void client.invalidateQueries({ queryKey: key }),
  });
}

/** Заявка S15 как карточка ленты — для списка S12 до ответа сервера: описание обрежет
 *  перечитанный список, расстояния у списка нет. */
export function jobCardOf(job: JobOut): JobCardOut {
  return {
    id: job.id,
    title: job.title,
    description: job.description,
    category_id: job.category_id,
    urgency: job.urgency,
    preferred_from: job.preferred_from,
    preferred_to: job.preferred_to,
    budget_type: job.budget_type,
    budget_min: job.budget_min,
    budget_max: job.budget_max,
    budget_unit: job.budget_unit,
    district_id: job.district_id,
    distance_m: null,
    photos: job.photos.slice(0, CARD_PHOTOS),
    photos_count: job.photos.length,
    responses_count: job.responses_count,
    max_responses: job.max_responses,
    published_at: job.published_at ?? job.created_at,
  };
}
