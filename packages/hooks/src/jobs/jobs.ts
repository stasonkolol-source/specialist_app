// Заявки клиента через API (DEVELOPMENT_PLAN 5.2): публикация черновика и сама заявка для S21.
// POST /jobs — с ключом идемпотентности черновика: повтор после обрыва сети вернёт ту же заявку;
// прямой запрос специалисту (5.6) — POST /specialists/{id}/requests с тем же ключом. Ответ сразу
// ложится в кэш заявки — S21 не перечитывает её.
import type { JobIn, JobOut } from '@sosed/api-client';
import {
  getJobsGetJobQueryKey,
  getJobsGetJobQueryOptions,
  jobsCreateJob,
  jobsRequestSpecialist,
} from '@sosed/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export const jobQueryKey = (jobId: string) => getJobsGetJobQueryKey(jobId);

/** Запрос заявки — один у S15, S23 и предзагрузки по нажатию на карточку. */
export function jobQueryOptions(jobId: string) {
  return getJobsGetJobQueryOptions(jobId, { query: { queryKey: jobQueryKey(jobId) } });
}

export function useJob(jobId: string | null) {
  return useQuery({ ...jobQueryOptions(jobId ?? ''), enabled: jobId !== null });
}

export interface PublishJob {
  body: JobIn;
  /** Idempotency-Key — ключ черновика. */
  key: string;
  /** Прямой запрос этому профилю: заявку увидит только его владелец. */
  directTo?: string | null;
}

export function useCreateJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key, directTo }: PublishJob) =>
      directTo
        ? jobsRequestSpecialist(directTo, body, { 'Idempotency-Key': key })
        : jobsCreateJob(body, { 'Idempotency-Key': key }),
    onSuccess: (job: JobOut) => client.setQueryData(jobQueryKey(job.id), job),
  });
}
