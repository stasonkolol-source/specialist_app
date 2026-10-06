// S21 «Заявка опубликована» (DEVELOPMENT_PLAN 5.2; UX_GUIDANCE №3 «что дальше»): что произошло,
// кто дальше и как об этом узнать, одно необязательное действие. Опубликована — «Отклики придут
// сюда и в Telegram — бот напишет о первом же. Заявка открыта до …» и «Хотите быстрее? Пригласите
// специалистов» из каталога (5.6); на проверке — сколько обычно ждать и что бот напишет об отклике;
// прямой запрос — «Запрос отправлен». Если боту нельзя писать, обещания «бот напишет» нет: вместо
// него «Разрешите боту писать…» и кнопка запроса (shared/BotChannel.tsx). MainButton «К заявке» —
// своя заявка S23, там же «Поделиться» (7.4). Ответ публикации — всегда «на проверке», а
// автопроверка публикует чистую заявку за доли секунды: пока заявка на проверке, экран
// перечитывает её и сам переходит в «опубликована». S21 заменил запись мастера в истории: «Назад» —
// туда, откуда мастер открыли, без истории — «Мои заявки».
import type { JobOut } from '@sosed/api-client';
import { useJobUntilReviewed } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Button, EmptyState, Heading, Icon, Text } from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import { useId } from 'react';

import { useBotChannel } from '../shared/BotChannel.tsx';
import { InviteList } from '../shared/InviteList.tsx';
import { useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS, HOME_PATH, JOBS_PATHS, managePath } from '../shared/paths.ts';

/** Сколько специалистов предложить на S21: остальные — в «Пригласить» на S23. */
const INVITES_SHOWN = 3;

export function PublishedScreen() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const { job: jobId } = useSearch({ from: CREATE_PATHS.done });
  const job = useJobUntilReviewed(jobId ?? null);
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

function Published({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const bot = useBotChannel();
  const published = job.status === 'published';
  const direct = job.visibility === 'direct';
  const open = published && !direct;
  const inviteId = useId();
  const title = direct
    ? 'published.titleDirect'
    : published
      ? 'published.titlePublished'
      : 'published.titlePending';
  // одна строка: что произошло, как узнать об откликах (бот — только если он может писать) и
  // сколько заявка открыта
  const happened = direct
    ? t(published ? 'published.textDirectPublished' : 'published.textDirectPending')
    : published
      ? null
      : t('published.textPending');
  // пока не знаем, может ли бот писать, — ни обещания, ни просьбы: строка не меняется на глазах
  // (настройки запрошены ещё на S20d)
  const channel =
    bot.writable === null
      ? null
      : bot.writable
        ? t(open ? 'published.textPublished' : 'published.botOn')
        : t('published.botOff');
  const until =
    open && job.expires_at
      ? t('published.openUntil', { date: format.dateGenitive(new Date(job.expires_at)) })
      : null;
  const asking = bot.writable === false && bot.canAsk;
  return (
    <section className="flex flex-col gap-5 px-4 pt-6 pb-6">
      <div className="flex flex-col items-center gap-3 text-center">
        <span className="flex size-20 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Icon name={published ? 'check' : 'clock'} size={32} />
        </span>
        <Heading variant="h2" as="h1">
          {t(title)}
        </Heading>
        <Text secondary>{[happened, channel, until].filter(Boolean).join(' ')}</Text>
        {asking && (
          <Button
            variant="secondary"
            icon="bell"
            onClick={() => bot.allow.mutate()}
            disabled={bot.allow.isPending}
            aria-busy={bot.allow.isPending}
          >
            {t('published.notifyAllow')}
          </Button>
        )}
      </div>
      {open && (
        <section aria-labelledby={inviteId} className="flex flex-col gap-2">
          <Heading variant="h3" as="h2" id={inviteId} className="px-1">
            {t('published.inviteTitle')}
          </Heading>
          <InviteList job={job} shown={INVITES_SHOWN} />
        </section>
      )}
    </section>
  );
}
