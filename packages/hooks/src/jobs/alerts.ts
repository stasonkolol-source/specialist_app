// Подписки на новые заявки (S18, S19; DEVELOPMENT_PLAN 5.7): до десяти, по порядку создания, у
// каждой — «N заявок за неделю». Новая подписка — с ключом идемпотентности: повтор после обрыва
// сети не создаст вторую. Ответ сервера — та же строка S18, что в списке: он сразу ложится в
// список (S18 открывается на новом списке), а сам список и лента «по моим подпискам» (её состав
// зависит от подписок) перечитываются в фоне. Переключатель S18 — оптимистично, с откатом.
import type { JobAlertIn, JobAlertOut, JobAlertPatchIn, JobAlertsOut } from '@sosed/api-client';
import {
  getJobsCountJobsQueryKey,
  getJobsListJobAlertsQueryKey,
  jobsCreateJobAlert,
  jobsDeleteJobAlert,
  jobsListJobAlerts,
  jobsUpdateJobAlert,
} from '@sosed/api-client';
import type { QueryClient } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { FEED_KEY } from './feed.ts';

/** Предел подписок, пока список не пришёл (сервер отдаёт свой в `limit`). */
export const ALERTS_MAX = 10;

export const alertsQueryKey = () => getJobsListJobAlertsQueryKey();
const COUNT_KEY = getJobsCountJobsQueryKey().slice(0, 1);

/** `enabled: false` — гостю подписок нет. */
export function useJobAlerts(enabled = true) {
  return useQuery({
    queryKey: alertsQueryKey(),
    queryFn: ({ signal }) => jobsListJobAlerts({ signal }),
    enabled,
  });
}

export interface CreateAlert {
  body: JobAlertIn;
  key: string;
}

export interface UpdateAlert {
  alertId: string;
  body: JobAlertPatchIn;
}

type Items = JobAlertOut[];

function setItems(client: QueryClient, apply: (items: Items) => Items) {
  client.setQueryData<JobAlertsOut>(alertsQueryKey(), (list) =>
    list ? { ...list, items: apply(list.items) } : list,
  );
}

/** Строка из ответа — на своё место; новая — в конец: порядок — по созданию. */
function placed(items: Items, alert: JobAlertOut): Items {
  return items.some((item) => item.id === alert.id)
    ? items.map((item) => (item.id === alert.id ? alert : item))
    : [...items, alert];
}

/** После правки: список с недельными числами и ленты «по моим подпискам» — в фоне. */
function refresh(client: QueryClient) {
  void client.invalidateQueries({ queryKey: alertsQueryKey() });
  void client.invalidateQueries({ queryKey: FEED_KEY });
  void client.invalidateQueries({ queryKey: COUNT_KEY });
}

export function useCreateAlert() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: CreateAlert) =>
      jobsCreateJobAlert(body, { 'Idempotency-Key': key }),
    onSuccess: (alert) => setItems(client, (items) => placed(items, alert)),
    onSettled: () => refresh(client),
  });
}

export function useUpdateAlert() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, body }: UpdateAlert) => jobsUpdateJobAlert(alertId, body),
    // переключатель S18 — сразу; ошибка вернёт прежнее состояние
    onMutate: async ({ alertId, body }) => {
      if (body.is_active === undefined || body.is_active === null) return { before: null };
      await client.cancelQueries({ queryKey: alertsQueryKey() });
      const before = client.getQueryData<JobAlertsOut>(alertsQueryKey()) ?? null;
      const active = body.is_active;
      setItems(client, (items) =>
        items.map((item) =>
          item.id === alertId
            ? { ...item, is_active: active, paused_until: active ? null : item.paused_until }
            : item,
        ),
      );
      return { before };
    },
    onError: (_error, _variables, context) => {
      if (context?.before) client.setQueryData(alertsQueryKey(), context.before);
    },
    onSuccess: (alert) => setItems(client, (items) => placed(items, alert)),
    onSettled: () => refresh(client),
  });
}

export function useDeleteAlert() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) => jobsDeleteJobAlert(alertId),
    onSuccess: (_result, alertId) =>
      setItems(client, (items) => items.filter((item) => item.id !== alertId)),
    onSettled: () => refresh(client),
  });
}

/** Присылает ли подписка заявки сейчас: включена и не на паузе из бота. */
export function receives(alert: JobAlertOut, now: Date = new Date()): boolean {
  return alert.is_active && (alert.paused_until === null || new Date(alert.paused_until) <= now);
}
