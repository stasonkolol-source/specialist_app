// S21 «Заявка опубликована» (DEVELOPMENT_PLAN 5.2): итог публикации — опубликована сразу или на
// проверке (обычно минуты). Если боту нельзя писать — контекстный запрос «Сообщать об откликах?»
// (shared/BotChannel.tsx). MainButton «К заявке» — своя заявка S23 (5.6). Опубликованной сразу —
// «Пригласите специалистов» из каталога (5.6); прямой запрос — «Запрос отправлен». Подписчикам
// заявка уходит сразу после публикации (5.7): пока число уведомлённых не пришло, экран перечитывает
// заявку пару раз и показывает «Уведомили N исполнителей рядом». «Поделиться в чат» (7.4) — у
// опубликованной не прямым запросом: ссылка в поле с «Скопировать» и «Отправить в чат Telegram» —
// карточка в выбор чата или ссылка. Ответ публикации — всегда «на проверке», а автопроверка
// публикует чистую заявку за доли секунды: пока заявка на проверке, экран перечитывает её и сам
// переходит в «опубликована» с приглашением специалистов. S21 заменил запись мастера в истории:
// «Назад» — туда, откуда мастер открыли, без истории — «Мои заявки».
import type { JobOut } from '@sosed/api-client';
import { shareVia, useJobUntilReviewed, useShareLink } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Button, Card, EmptyState, Heading, Icon, IconButton, Input, Text } from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import { useEffect, useId } from 'react';

import { BotChannel } from '../shared/BotChannel.tsx';
import { InviteList } from '../shared/InviteList.tsx';
import { useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS, HOME_PATH, JOBS_PATHS, managePath } from '../shared/paths.ts';
import { shareable, useJobShare } from '../shared/share.tsx';

/** Подписчиков считает задача после публикации: через пару секунд число уже есть. */
const NOTIFIED_RETRY_MS = [2_000, 6_000];

export function PublishedScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const { job: jobId } = useSearch({ from: CREATE_PATHS.done });
  const job = useJobUntilReviewed(jobId ?? null);
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
  // «Назад» в мастер не ведёт: черновика больше нет, заявка уже создана, а его шаги S21 заменил
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.mine, replace: true });
  });
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

/** «Поделиться в чат»: ссылка на заявку (у вошедшего — с его кодом) и отправка в чат Telegram. */
function ShareToChat({ jobId }: { jobId: string }) {
  const { t } = useTranslation();
  const platform = usePlatform();
  const titleId = useId();
  const link = useShareLink({ type: 'job', id: jobId });
  const sharing = useJobShare(jobId);
  if (link.isError) return null;
  const out = link.data;
  return (
    <Card as="section" aria-labelledby={titleId}>
      <div className="flex flex-col gap-1">
        <Heading variant="h3" as="h2" id={titleId}>
          {t('share.toChat')}
        </Heading>
        <Text variant="cap">{t('share.toChatHint')}</Text>
      </div>
      <Input
        icon="link"
        readOnly
        value={out ? out.url.replace(/^https:\/\//, '') : ''}
        aria-label={t('share.link')}
        aria-busy={!out || undefined}
        suffix={
          <IconButton
            plain
            icon="copy"
            label={t('share.copy')}
            className="-mr-3"
            onClick={() => out && sharing.copy(out.url)}
          />
        }
      />
      <Button
        variant="secondary"
        icon="send"
        full
        disabled={!out}
        onClick={() => out && void shareVia(platform, out)}
      >
        {t('share.send')}
      </Button>
      {sharing.notice}
    </Card>
  );
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
      {shareable(job) && <ShareToChat jobId={job.id} />}
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
