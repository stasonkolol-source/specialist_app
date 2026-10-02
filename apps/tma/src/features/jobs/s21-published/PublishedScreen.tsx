// S21 «Заявка опубликована» (DEVELOPMENT_PLAN 5.2): итог публикации — опубликована сразу или на
// проверке (обычно минуты). Если боту нельзя писать — контекстный запрос «Сообщать об откликах?»:
// requestWriteAccess клиента Telegram, затем POST /me/telegram/write-access. «Пригласить
// специалистов» (5.6), «Поделиться в чат» (7.4) и «К заявке» (S23, 5.6) — в своих шагах; пока
// MainButton «Готово» ведёт на Главную. Число уведомлённых исполнителей появится с подписками (5.7).
import type { JobOut } from '@sosed/api-client';
import {
  getNotificationsGetNotificationSettingsQueryKey,
  notificationsGrantTelegramWriteAccess,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import { useJob } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Banner, Button, Card, EmptyState, Heading, Icon, Text } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearch } from '@tanstack/react-router';

import { useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS, HOME_PATH } from '../shared/paths.ts';

export function PublishedScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const { job: jobId } = useSearch({ from: CREATE_PATHS.done });
  const job = useJob(jobId ?? null);
  const home = () => void router.navigate({ to: HOME_PATH, replace: true });
  // «Назад» в мастер не ведёт: черновика больше нет, заявка уже создана
  useBackButton(null);
  useStepButton({ text: t('published.done'), onClick: home });

  if (!jobId || job.isError) {
    return (
      <section className="px-4 pt-6">
        <EmptyState as="h1" icon="jobs" title={t('published.missing')} />
      </section>
    );
  }
  if (!job.data) return null;
  return <Published job={job.data} />;
}

function Published({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const published = job.status === 'published';
  return (
    <section className="flex flex-col gap-5 px-4 pt-6 pb-6">
      <div className="flex flex-col items-center gap-3 text-center">
        <span className="flex size-20 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Icon name={published ? 'check' : 'clock'} size={32} />
        </span>
        <Heading variant="h2" as="h1">
          {t(published ? 'published.titlePublished' : 'published.titlePending')}
        </Heading>
        <Text secondary>
          {t(published ? 'published.textPublished' : 'published.textPending')}
        </Text>
      </div>
      <BotChannel />
    </section>
  );
}

/** Боту нельзя писать (канала нет или бота остановили) — предложить разрешить. */
function BotChannel() {
  const { t } = useTranslation('jobs');
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const settings = useNotificationsGetNotificationSettings();
  const allow = useMutation({
    mutationFn: async () => {
      if (!(await platform.requestWriteAccess().catch(() => false))) throw new Error('declined');
      return notificationsGrantTelegramWriteAccess();
    },
    onSuccess: (telegram) => {
      queryClient.setQueryData(
        getNotificationsGetNotificationSettingsQueryKey(),
        (current: typeof settings.data) => current && { ...current, telegram },
      );
    },
  });
  const channel = settings.data?.telegram;
  if (!settings.data || !platform.capabilities.requestWriteAccess) return null;
  if (channel?.writable) {
    // разрешили только что — подтверждаем; было разрешено раньше — нечего показывать
    return allow.isSuccess ? (
      <Banner tone="ok" icon="bell" role="status">
        {t('published.notifyOn')}
      </Banner>
    ) : null;
  }
  return (
    <Card className="flex flex-col gap-2">
      <Heading variant="h3" as="h2">
        {t('published.notifyTitle')}
      </Heading>
      <Text secondary>{t('published.notifyText')}</Text>
      <Button
        variant="secondary"
        icon="bell"
        onClick={() => allow.mutate()}
        disabled={allow.isPending}
        aria-busy={allow.isPending}
      >
        {t('published.notifyAllow')}
      </Button>
      {allow.isError && (
        <Text variant="cap" className="text-danger">
          {t('published.notifyDenied')}
        </Text>
      )}
    </Card>
  );
}
