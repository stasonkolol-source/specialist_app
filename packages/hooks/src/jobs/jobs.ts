// Заявки клиента через API (DEVELOPMENT_PLAN 5.2): публикация черновика и сама заявка для S21.
// POST /jobs — с ключом идемпотентности черновика: повтор после обрыва сети вернёт ту же заявку;
// прямой запрос специалисту (5.6) — POST /specialists/{id}/requests с тем же ключом. Ответ сразу
// ложится в кэш заявки — S21 рисуется без загрузки. Ответ всегда «на проверке», а автопроверка
// чистого текста публикует заявку через доли секунды (модератор — через минуты): пока заявка на
// проверке, S21 и S23 перечитывают её всё реже (REVIEW_POLL_MS). Второе нажатие, пришедшее, пока
// первый запрос с тем же ключом ещё идёт (409 `idempotency_in_progress`), дожидается его и получает
// ту же заявку. Ключ, уже потраченный на другое тело (черновик поправили после публикации, которая
// выглядела неудачной, — 422 `idempotency_key_reused`), меняется: новое тело — новый ключ.
import type { JobIn, JobOut } from '@sosed/api-client';
import {
  ApiError,
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

/** Перечитывания заявки на проверке: первое — через секунду, дальше реже, потом — раз в 15 с. */
export const REVIEW_POLL_MS = [1_000, 2_000, 4_000, 8_000, 15_000] as const;

/** Через сколько перечитать заявку: на проверке — по REVIEW_POLL_MS (`updates` — сколько раз
 *  она уже приходила), иначе — не нужно. */
export function reviewPollMs(job: JobOut | undefined, updates: number): number | false {
  if (job?.status !== 'pending_moderation') return false;
  const step = Math.min(Math.max(updates - 1, 0), REVIEW_POLL_MS.length - 1);
  return REVIEW_POLL_MS[step] ?? false;
}

/** Итог публикации S21: заявка из ответа POST; пока она на проверке — перечитывается, и экран
 *  сам переходит в «опубликована» (или «нужно исправить»). */
export function useJobUntilReviewed(jobId: string | null) {
  return useQuery({
    ...jobQueryOptions(jobId ?? ''),
    enabled: jobId !== null,
    refetchInterval: (query) => reviewPollMs(query.state.data, query.state.dataUpdateCount),
  });
}

export interface PublishJob {
  body: JobIn;
  /** Idempotency-Key — ключ черновика. */
  key: string;
  /** Прямой запрос этому профилю: заявку увидит только его владелец. */
  directTo?: string | null;
  /** Ключ уже потрачен на другое тело: новый ключ для этой отправки (черновик его запомнит —
   *  повтор той же отправки пойдёт с ним). */
  rekey?: () => string;
}

/** Паузы перед повтором, пока первый запрос с тем же ключом ещё выполняется. */
export const IN_PROGRESS_RETRY_MS = [500, 1_000, 2_000, 4_000] as const;

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const failedWith = (error: unknown, code: string) =>
  error instanceof ApiError && error.code === code;

export function useCreateJob({ sleep = wait }: { sleep?: (ms: number) => Promise<void> } = {}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, key, directTo, rekey }: PublishJob): Promise<JobOut> => {
      let current = key;
      let pauses = 0;
      for (;;) {
        try {
          return await (directTo
            ? jobsRequestSpecialist(directTo, body, { 'Idempotency-Key': current })
            : jobsCreateJob(body, { 'Idempotency-Key': current }));
        } catch (error) {
          // двойное нажатие: первый запрос ещё идёт — дождаться его ответа тем же ключом
          const pause = IN_PROGRESS_RETRY_MS[pauses];
          if (failedWith(error, 'idempotency_in_progress') && pause !== undefined) {
            pauses += 1;
            await sleep(pause);
            continue;
          }
          if (failedWith(error, 'idempotency_key_reused') && rekey && current === key) {
            current = rekey();
            continue;
          }
          throw error;
        }
      }
    },
    onSuccess: (job: JobOut) => client.setQueryData(jobQueryKey(job.id), job),
  });
}
