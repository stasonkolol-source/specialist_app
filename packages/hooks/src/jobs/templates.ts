// Шаблоны откликов (S16, S57; DEVELOPMENT_PLAN 5.5): не больше двух, первый — основной; S16
// подставляет основной в пустую форму. Новый шаблон — с ключом идемпотентности: повтор после обрыва
// сети не создаст второй. После любого изменения список перечитывается.
import type { ResponseTemplateIn, ResponseTemplatePatchIn } from '@sosed/api-client';
import {
  getJobsListResponseTemplatesQueryKey,
  jobsCreateResponseTemplate,
  jobsDeleteResponseTemplate,
  jobsListResponseTemplates,
  jobsUpdateResponseTemplate,
} from '@sosed/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export const templatesQueryKey = () => getJobsListResponseTemplatesQueryKey();

/** `enabled: false` — гостю шаблонов нет. */
export function useResponseTemplates(enabled = true) {
  return useQuery({
    queryKey: templatesQueryKey(),
    queryFn: ({ signal }) => jobsListResponseTemplates({ signal }),
    enabled,
  });
}

export interface CreateTemplate {
  body: ResponseTemplateIn;
  key: string;
}

export interface UpdateTemplate {
  templateId: string;
  body: ResponseTemplatePatchIn;
}

function useTemplatesMutation<T>(mutationFn: (variables: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => client.invalidateQueries({ queryKey: templatesQueryKey() }),
  });
}

export const useCreateTemplate = () =>
  useTemplatesMutation(({ body, key }: CreateTemplate) =>
    jobsCreateResponseTemplate(body, { 'Idempotency-Key': key }),
  );

export const useUpdateTemplate = () =>
  useTemplatesMutation(({ templateId, body }: UpdateTemplate) =>
    jobsUpdateResponseTemplate(templateId, body),
  );

export const useDeleteTemplate = () =>
  useTemplatesMutation((templateId: string) => jobsDeleteResponseTemplate(templateId));
