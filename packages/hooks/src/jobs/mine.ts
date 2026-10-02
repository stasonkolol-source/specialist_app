// Свои заявки клиента (S22, S23; DEVELOPMENT_PLAN 5.6): список с числом новых откликов, отклики
// карточками — опрос раз в 15 секунд, пока экран открыт; закрыть с причиной, продлить, пригласить
// специалистов. После действия заявка, список и счётчики перечитываются.
import type { JobCloseInReason, JobOut } from '@sosed/api-client';
import {
  getJobsListJobInvitesQueryKey,
  getJobsListMyJobsQueryKey,
  getSession,
  getViewsListResponseCardsQueryKey,
  jobsCloseJob,
  jobsExtendJob,
  jobsInviteSpecialists,
  jobsListJobInvites,
  jobsListMyJobs,
  viewsListResponseCards,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { FEED_KEY } from './feed.ts';
import { jobQueryKey } from './jobs.ts';

/** Опрос откликов на S23 (ARCHITECTURE §11): новые появляются без «потяните, чтобы обновить». */
export const RESPONSES_POLL_MS = 15_000;

export const myJobsQueryKey = () => getJobsListMyJobsQueryKey();
export const responseCardsQueryKey = (jobId: string) => getViewsListResponseCardsQueryKey(jobId);

/** Все свои заявки, новые первыми; гостю — нечего запрашивать. */
export function useMyJobs() {
  return useQuery({
    queryKey: myJobsQueryKey(),
    queryFn: ({ signal }) => jobsListMyJobs(undefined, { signal }),
    enabled: getSession() !== null,
  });
}

/** Отклики своей заявки карточками; сервер отмечает их просмотренными — бейдж S22 гаснет. */
export function useResponseCards(jobId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: responseCardsQueryKey(jobId ?? ''),
    queryFn: async ({ signal }) => {
      const cards = await viewsListResponseCards(jobId ?? '', { signal });
      void client.invalidateQueries({ queryKey: myJobsQueryKey() });
      return cards;
    },
    enabled: jobId !== null,
    refetchInterval: RESPONSES_POLL_MS,
  });
}

async function refresh(client: QueryClient, job: JobOut) {
  client.setQueryData(jobQueryKey(job.id), job);
  await Promise.all([
    client.invalidateQueries({ queryKey: myJobsQueryKey() }),
    client.invalidateQueries({ queryKey: FEED_KEY }),
  ]);
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
