// S21 «Заявка опубликована» (DEVELOPMENT_PLAN 5.2): итог публикации — опубликована сразу или на
// проверке (обычно минуты). Если боту нельзя писать — контекстный запрос «Сообщать об откликах?»
// (shared/BotChannel.tsx). MainButton «К заявке» — своя заявка S23 (5.6). Опубликованной сразу —
// «Пригласите специалистов» из каталога (5.6); прямой запрос — «Запрос отправлен». «Поделиться в
// чат» — 7.4. Подписчикам заявка уходит сразу после публикации (5.7): пока число уведомлённых не
// пришло, экран перечитывает заявку пару раз и показывает «Уведомили N исполнителей рядом».
import type { JobOut } from '@sosed/api-client';
import { useJob } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { EmptyState, Heading, Icon, Text } from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import { useEffect, useId } from 'react';

import { BotChannel } from '../shared/BotChannel.tsx';
import { InviteList } from '../shared/InviteList.tsx';
import { useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS, HOME_PATH, managePath } from '../shared/paths.ts';

/** Подписчиков считает задача после публикации: через пару секунд число уже есть. */
const NOTIFIED_RETRY_MS = [2_000, 6_000];

export function PublishedScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const { job: jobId } = useSearch({ from: CREATE_PATHS.done });
  const job = useJob(jobId ?? null);
  const { refetch } = job;
  const counting =
    job.data?.status === 'published' &&
    job.data.visibility !== 'direct' &&
    (job.data.notified_count ?? 0) === 0;
  useEffect(() => {
    if (!counting) return undefined;
    const timers = NOTIFIED_RETRY_MS.map((delay) => window.setTimeout(() => void refetch(), delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [counting, refetch]);
  const toJob = () =>
    void router.navigate(
      jobId ? { to: managePath(jobId), replace: true } : { to: HOME_PATH, replace: true },
    );
  // «Назад» в мастер не ведёт: черновика больше нет, заявка уже создана
  useBackButton(null);
  useStepButton({ text: t('published.toJob'), onClick: toJob });

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
  const direct = job.visibility === 'direct';
  const inviteId = useId();
  const notified = job.notified_count ?? 0;
  const title = direct
    ? 'published.titleDirect'
    : published
      ? 'published.titlePublished'
      : 'published.titlePending';
  const text = direct
    ? published
      ? 'published.textDirectPublished'
      : 'published.textDirectPending'
    : published
      ? 'published.textPublished'
      : 'published.textPending';
  return (
    <section className="flex flex-col gap-5 px-4 pt-6 pb-6">
      <div className="flex flex-col items-center gap-3 text-center">
        <span className="flex size-20 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Icon name={published ? 'check' : 'clock'} size={32} />
        </span>
        <Heading variant="h2" as="h1">
          {t(title)}
        </Heading>
        <Text secondary>
          {published && !direct && notified > 0
            ? t('published.notified', { count: notified })
            : t(text)}
        </Text>
      </div>
      <BotChannel
        texts={{
          title: t('published.notifyTitle'),
          text: t('published.notifyText'),
          allow: t('published.notifyAllow'),
          on: t('published.notifyOn'),
          denied: t('published.notifyDenied'),
        }}
      />
      {published && !direct && (
        <section aria-labelledby={inviteId} className="flex flex-col gap-2">
          <div className="flex flex-col gap-1 px-1">
            <Heading variant="h3" as="h2" id={inviteId}>
              {t('manage.inviteTitle')}
            </Heading>
            <Text variant="cap">{t('manage.inviteHint')}</Text>
          </div>
          <InviteList job={job} />
        </section>
      )}
    </section>
  );
}
