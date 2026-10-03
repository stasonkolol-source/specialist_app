// Главный запрос экрана подробностей по намерению перейти (app/intent.ts): профиль S08, заявка S15,
// последние сообщения S30 — к открытию экрана ответ уже в пути или в кэше. Ключи и свежесть — из
// фабрик @sosed/hooks: те же, что у хуков экранов. Ошибки — тихие (SILENT): экран перечитает
// запрос сам и покажет ошибку как обычно. Своим чанком: первому экрану этот код не нужен.
import { getSession } from '@sosed/api-client';
import { chatQueryOptions, jobQueryOptions, specialistCardQueryOptions } from '@sosed/hooks';
import { currentLocale } from '@sosed/i18n';

import { CARD_PATHS } from '../features/catalog/index.ts';
import { JOBS_PATHS, jobIdOf } from '../features/jobs/index.ts';
import { MESSAGES_PATHS } from '../features/messages/index.ts';
import type { Assembled } from './bootstrap.ts';
import { SILENT } from './query.ts';

export function prefetchScreen(
  { router, queryClient, i18n }: Pick<Assembled, 'router' | 'queryClient' | 'i18n'>,
  href: string,
): void {
  const pathname = href.split(/[?#]/)[0] ?? href;
  const [, params, route] = router.getMatchedRoutes(pathname);
  switch (route?.fullPath) {
    case CARD_PATHS.profile: {
      const { profileId } = params;
      if (!profileId) return;
      const options = specialistCardQueryOptions(profileId, currentLocale(i18n));
      void queryClient.prefetchQuery({ ...options, meta: SILENT });
      return;
    }
    case JOBS_PATHS.job: {
      const jobId = jobIdOf(params.jobId ?? '');
      if (jobId) void queryClient.prefetchQuery({ ...jobQueryOptions(jobId), meta: SILENT });
      return;
    }
    case MESSAGES_PATHS.chat: {
      // диалог — только вошедшему (маршрут требует входа)
      const { conversationId } = params;
      if (!conversationId || getSession() === null) return;
      void queryClient.prefetchQuery({ ...chatQueryOptions(conversationId), meta: SILENT });
      return;
    }
    default:
      return;
  }
}
