// Шаблоны откликов (S16, S57; DEVELOPMENT_PLAN 5.5): не больше двух, первый — основной; S16
// подставляет основной в пустую форму. Новый шаблон — с ключом идемпотентности: повтор после обрыва
// сети не создаст второй. Ответ сервера сразу ложится в список (шторка закрывается на новом
// списке), а сам список перечитывается в фоне: порядок и «основной» решает сервер.
import type {
  ResponseTemplateIn,
  ResponseTemplateOut,
  ResponseTemplatePatchIn,
  ResponseTemplatesOut,
} from '@sosed/api-client';
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

type Items = ResponseTemplateOut[];

/** Шаблон из ответа — на своё место; основной — первым, у остальных отметка снимается. */
function placed(items: Items, template: ResponseTemplateOut): Items {
  const others = items.filter((item) => item.id !== template.id);
  if (!template.primary) {
    const at = items.findIndex((item) => item.id === template.id);
    return at < 0 ? [...others, template] : items.map((item, i) => (i === at ? template : item));
  }
  return [template, ...others.map((item) => ({ ...item, primary: false }))];
}

function useTemplatesMutation<T, R>(
  mutationFn: (variables: T) => Promise<R>,
  apply: (items: Items, result: R, variables: T) => Items,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (result, variables) =>
      client.setQueryData<ResponseTemplatesOut>(templatesQueryKey(), (list) =>
        list ? { ...list, items: apply(list.items, result, variables) } : list,
      ),
    onSettled: () => void client.invalidateQueries({ queryKey: templatesQueryKey() }),
  });
}

export const useCreateTemplate = () =>
  useTemplatesMutation(
    ({ body, key }: CreateTemplate) => jobsCreateResponseTemplate(body, { 'Idempotency-Key': key }),
    placed,
  );

export const useUpdateTemplate = () =>
  useTemplatesMutation(
    ({ templateId, body }: UpdateTemplate) => jobsUpdateResponseTemplate(templateId, body),
    placed,
  );

export const useDeleteTemplate = () =>
  useTemplatesMutation(
    (templateId: string) => jobsDeleteResponseTemplate(templateId),
    (items, _result, templateId) => {
      const left = items.filter((item) => item.id !== templateId);
      // «первый — основной»: удалили основной — основным стал следующий
      return left.some((item) => item.primary)
        ? left
        : left.map((item, index) => ({ ...item, primary: index === 0 }));
    },
  );
