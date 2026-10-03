// Свои заявки клиента (S22, S23; DEVELOPMENT_PLAN 5.6): список с числом новых откликов, отклики
// карточками — опрос раз в 15 секунд, пока экран открыт; закрыть с причиной, продлить, пригласить
// специалистов. После действия заявка из ответа сервера сразу ложится в кэш и в список, а список и
// лента перечитываются в фоне: экран действия их не ждёт.
import type { JobCloseInReason, JobIn, JobOut, JobsOut } from '@sosed/api-client';
import {
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
import { jobQueryKey } from './jobs.ts';

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

/** Своя заявка (S23). В списке «Мои заявки» — та же JobOut целиком (без блока клиента, его на
 *  своей заявке нет): пока она перечитывается, экран рисует её из списка, с временем того ответа —
 *  устаревшая перечитается сразу. Нет в списке — обычная загрузка. */
export function useOwnJob(jobId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ''),
    queryFn: ({ signal }) => jobsGetJob(jobId ?? '', { signal }),
    enabled: jobId !== null,
    initialData: () =>
      client.getQueryData<JobsOut>(myJobsQueryKey())?.items.find((job) => job.id === jobId),
    initialDataUpdatedAt: () => client.getQueryState(myJobsQueryKey())?.dataUpdatedAt,
  });
}

/** Отклики своей заявки карточками; сервер отмечает их просмотренными — бейдж S22 гаснет. Список
 *  заявок и бейдж «Заявки» перечитываются, только когда в списке у заявки были новые отклики, а не
 *  на каждый опрос. */
export function useResponseCards(jobId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: responseCardsQueryKey(jobId ?? ''),
    queryFn: async ({ signal }) => {
      const cards = await viewsListResponseCards(jobId ?? '', { signal });
      const listed = client
        .getQueryData<JobsOut>(myJobsQueryKey())
        ?.items.find((job) => job.id === jobId);
      if ((listed?.new_responses ?? 0) > 0) {
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
}

/** «Изменить» на S23: заявка целиком, с If-Match; отклонённая и заметно изменённая — снова на
 *  проверку (решает сервер). */
export function useUpdateJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, version, body }: UpdateJob) =>
      jobsUpdateJob(jobId, body, { 'If-Match': `"${version}"` }),
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
