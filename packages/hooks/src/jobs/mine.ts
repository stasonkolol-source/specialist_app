// Свои заявки клиента (S22, S23; DEVELOPMENT_PLAN 5.6): список с числом новых откликов, отклики
// карточками — опрос раз в 15 секунд, пока экран открыт; закрыть с причиной, продлить, пригласить
// специалистов. После действия заявка из ответа сервера сразу ложится в кэш и в список, а список и
// лента перечитываются в фоне: экран действия их не ждёт. Сама заявка на S23 перечитывается при
// каждом открытии и вместе с откликами (счётчики мест и просмотров), а на проверке — чаще: её
// статус и версию (If-Match правки) меняет и автопроверка.
import type { JobCloseInReason, JobIn, JobOut, JobsOut } from '@sosed/api-client';
import {
  ApiError,
  getJobsListJobInvitesQueryKey,
  getJobsListMyJobsQueryKey,
  getSession,
  getViewsGetBadgesQueryKey,
  getViewsListResponseCardsQueryKey,
  jobsCloseJob,
  jobsGetJob,
  jobsExtendJob,
  jobsInviteSpecialists,
  jobsListJobInvites,
  jobsListMyJobs,
  jobsUpdateJob,
  viewsListResponseCards,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { FEED_KEY } from './feed.ts';
import { jobQueryKey, reviewPollMs } from './jobs.ts';

/** Опрос откликов на S23 (ARCHITECTURE §11): новые появляются без «потяните, чтобы обновить». */
export const RESPONSES_POLL_MS = 15_000;

export const myJobsQueryKey = () => getJobsListMyJobsQueryKey();
export const responseCardsQueryKey = (jobId: string) => getViewsListResponseCardsQueryKey(jobId);

/** Запрос своих заявок — один у хука и у предзагрузки Главной после входа. */
export function myJobsQueryOptions() {
  return queryOptions({
    queryKey: myJobsQueryKey(),
    queryFn: ({ signal }) => jobsListMyJobs(undefined, { signal }),
    enabled: getSession() !== null,
  });
}

/** Все свои заявки, новые первыми; гостю — нечего запрашивать. */
export function useMyJobs() {
  return useQuery(myJobsQueryOptions());
}

/** Как часто перечитывать свою заявку на S23: на проверке — по REVIEW_POLL_MS, открытую — вместе с
 *  откликами, остальные не меняются сами. */
export function ownJobPollMs(job: JobOut | undefined, updates: number): number | false {
  if (job?.status === 'published') return RESPONSES_POLL_MS;
  return reviewPollMs(job, updates);
}

/** Своя заявка (S23). В списке «Мои заявки» — та же JobOut целиком (без блока клиента, его на
 *  своей заявке нет): пока она перечитывается, экран рисует её из списка. Нет в списке — обычная
 *  загрузка. Перечитывается при каждом открытии экрана — даже из свежего кэша (ответ публикации
 *  или правки — «на проверке» прошлой версии) — и дальше по ownJobPollMs. */
export function useOwnJob(jobId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ''),
    queryFn: ({ signal }) => jobsGetJob(jobId ?? '', { signal }),
    enabled: jobId !== null,
    initialData: () =>
      client.getQueryData<JobsOut>(myJobsQueryKey())?.items.find((job) => job.id === jobId),
    initialDataUpdatedAt: () => client.getQueryState(myJobsQueryKey())?.dataUpdatedAt,
    refetchOnMount: 'always',
    refetchInterval: (query) => ownJobPollMs(query.state.data, query.state.dataUpdateCount),
  });
}

/** Отклики своей заявки карточками; сервер отмечает их просмотренными — бейдж S22 гаснет. Список
 *  заявок и бейдж «Заявки» перечитываются, только когда были новые отклики — у заявки в списке или
 *  среди самих карточек (заявку открыли из бота, списка в кэше нет): бейдж гаснет, как только
 *  заявку открыли, а не через минуту опроса. На каждый опрос — нет. */
export function useResponseCards(jobId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: responseCardsQueryKey(jobId ?? ''),
    queryFn: async ({ signal }) => {
      const cards = await viewsListResponseCards(jobId ?? '', { signal });
      const listed = client
        .getQueryData<JobsOut>(myJobsQueryKey())
        ?.items.find((job) => job.id === jobId);
      if ((listed?.new_responses ?? 0) > 0 || cards.items.some((card) => card.is_new)) {
        void client.invalidateQueries({ queryKey: myJobsQueryKey() });
        void client.invalidateQueries({ queryKey: getViewsGetBadgesQueryKey() });
      }
      return cards;
    },
    enabled: jobId !== null,
    refetchInterval: RESPONSES_POLL_MS,
  });
}

function refresh(client: QueryClient, job: JobOut): void {
  client.setQueryData(jobQueryKey(job.id), job);
  // «N новых» считает только список: у ответа действия их нет
  const listed = (item: JobOut) =>
    item.id === job.id ? { ...job, new_responses: item.new_responses } : item;
  client.setQueryData<JobsOut>(myJobsQueryKey(), (list) =>
    list ? { ...list, items: list.items.map(listed) } : list,
  );
  void client.invalidateQueries({ queryKey: myJobsQueryKey() });
  void client.invalidateQueries({ queryKey: FEED_KEY });
}

export interface CloseJob {
  jobId: string;
  reason: JobCloseInReason;
}

export function useCloseJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, reason }: CloseJob) => jobsCloseJob(jobId, { reason }),
    onSuccess: (job) => refresh(client, job),
  });
}

export interface UpdateJob {
  jobId: string;
  /** Версия, которую клиент правил: If-Match — чужая правка между ними даст 412. */
  version: number;
  body: JobIn;
  /** Заявка, с которой начали правку: с ней сравнивается текущая, если версия ушла вперёд. */
  base?: JobOut;
}

/** Поля, которые правит владелец (тело PATCH): по ним видно, правили ли заявку в другом месте. */
const OWNER_FIELDS = [
  'title',
  'description',
  'category_id',
  'urgency',
  'preferred_from',
  'preferred_to',
  'budget_type',
  'budget_min',
  'budget_max',
  'budget_unit',
  'city_id',
  'district_id',
  'address_private',
  'languages',
  'media_ids',
] as const satisfies readonly (keyof JobOut)[];

/** Те же поля владельца у двух версий заявки: разница — только в статусе и служебных полях. */
export function sameOwnerFields(a: JobOut, b: JobOut): boolean {
  const fields = (job: JobOut) => JSON.stringify(OWNER_FIELDS.map((field) => job[field]));
  return fields(a) === fields(b);
}

/** Правку не сохранили: пока её вносили, саму заявку изменили в другом месте. `current` — какая
 *  она сейчас: мастер показывает её, правку вносят заново. */
export class StaleJobError extends Error {
  override readonly name = 'StaleJobError';
  readonly current: JobOut;

  constructor(current: JobOut) {
    super('stale_version');
    this.current = current;
  }
}

/** Повторов правки, если версия ушла вперёд без чужой правки. */
const STALE_RETRIES = 2;

const isStale = (error: unknown) =>
  error instanceof ApiError && error.status === 412 && error.code === 'stale_version';

/** «Изменить» на S23: заявка целиком, с If-Match; отклонённая и заметно изменённая — снова на
 *  проверку (решает сервер). Версию двигает не только правка: автопроверка публикует заявку,
 *  модератор возвращает её — тогда 412 ложный. Мастер перечитывает заявку: поля владельца те же,
 *  что в начале правки, — та же правка уходит с новой версией; другие — StaleJobError. */
export function useUpdateJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ jobId, version, body, base }: UpdateJob): Promise<JobOut> => {
      let ifMatch = version;
      for (let retry = 0; ; retry += 1) {
        try {
          return await jobsUpdateJob(jobId, body, { 'If-Match': `"${ifMatch}"` });
        } catch (error) {
          if (!isStale(error) || !base || retry >= STALE_RETRIES) throw error;
          const current = await jobsGetJob(jobId);
          client.setQueryData(jobQueryKey(jobId), current);
          if (!sameOwnerFields(current, base)) throw new StaleJobError(current);
          ifMatch = current.version;
        }
      }
    },
    // ответ правки — «на проверке» этой версии, а автопроверка уже двигает её дальше: S23, куда
    // ведёт сохранение, перечитает заявку сразу при открытии (useOwnJob)
    onSuccess: (job) => refresh(client, job),
  });
}

export function useExtendJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => jobsExtendJob(jobId),
    onSuccess: (job) => refresh(client, job),
  });
}

export const jobInvitesQueryKey = (jobId: string) => getJobsListJobInvitesQueryKey(jobId);

/** Кого уже пригласили в свою заявку: «Приглашён» вместо кнопки. */
export function useJobInvites(jobId: string | null) {
  return useQuery({
    queryKey: jobInvitesQueryKey(jobId ?? ''),
    queryFn: ({ signal }) => jobsListJobInvites(jobId ?? '', { signal }),
    enabled: jobId !== null,
  });
}

export interface InviteSpecialists {
  jobId: string;
  profileIds: string[];
}

export function useInviteSpecialists() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, profileIds }: InviteSpecialists) =>
      jobsInviteSpecialists(jobId, { profile_ids: profileIds }),
    onSuccess: (invites, { jobId }) => client.setQueryData(jobInvitesQueryKey(jobId), invites),
  });
}
