// S21 «Заявка опубликована» (DEVELOPMENT_PLAN 5.2; UX_GUIDANCE №3 «что дальше»): что произошло,
// кто дальше и как об этом узнать, одно необязательное действие. Опубликована — «Разослали N
// специалистам рядом» (когда подписчики уже посчитаны), «Отклики придут сюда и в Telegram — бот
// напишет о первом же. Заявка открыта до …» и «Хотите быстрее? Пригласите специалистов» из каталога
// (5.6); в каталоге пригласить некого — вместо тупика «Поделитесь заявкой в чате района» и
// «Поделиться заявкой» (7.4; аудит клиента п. 1). На проверке — сколько обычно ждать и что бот
// напишет об отклике; прямой запрос — «Запрос отправлен». Если боту нельзя писать, обещания «бот
// напишет» нет: вместо него «Разрешите боту писать…» и кнопка запроса (shared/BotChannel.tsx).
// MainButton «К заявке» — своя заявка S23, там же «Поделиться». Ответ публикации — всегда «на
// проверке», а автопроверка публикует чистую заявку за доли секунды: пока заявка на проверке, экран
// перечитывает её и сам переходит в «опубликована»; подписчиков задача считает сразу после
// публикации — пока их нет, экран перечитывает заявку ещё пару раз. S21 заменил запись мастера в
// истории: «Назад» — туда, откуда мастер открыли, без истории — «Мои заявки».
import type { JobOut } from '@sosed/api-client';
import { useJobUntilReviewed } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import { Button, EmptyState, Heading, Icon, Text } from '@sosed/ui-web';
import { useRouter, useSearch } from '@tanstack/react-router';
import { useEffect, useId } from 'react';

import { useBotChannel } from '../shared/BotChannel.tsx';
import { InviteList, useNobodyToInvite } from '../shared/InviteList.tsx';
import { useStepButton } from '../shared/flow.ts';
import { CREATE_PATHS, HOME_PATH, JOBS_PATHS, managePath } from '../shared/paths.ts';
import { useJobShare } from '../shared/share.tsx';

/** Сколько специалистов предложить на S21: остальные — в «Пригласить» на S23. */
const INVITES_SHOWN = 3;
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

function Published({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const bot = useBotChannel();
  const published = job.status === 'published';
  const direct = job.visibility === 'direct';
  const open = published && !direct;
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
  const notified =
    open && (job.notified_count ?? 0) > 0
      ? t('manage.notified', { count: job.notified_count })
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
        <Text secondary>{[notified, happened, channel, until].filter(Boolean).join(' ')}</Text>
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
      {open && <Faster job={job} />}
    </section>
  );
}

/** Как получить отклики быстрее: пригласить специалистов из каталога, а если пригласить некого —
 *  поделиться заявкой в чате района (одно действие вместо тупика «специалистов рядом нет»). */
function Faster({ job }: { job: JobOut }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const nobody = useNobodyToInvite(job);
  const sharing = useJobShare(job.id);
  const titleId = useId();
  if (nobody) {
    return (
      <section aria-labelledby={titleId} className="flex flex-col gap-2">
        <Heading variant="h3" as="h2" id={titleId} className="px-1">
          {t('published.shareTitle')}
        </Heading>
        <Text secondary className="px-1">
          {t('published.shareText')}
        </Text>
        <Button
          variant="secondary"
          icon="share"
          full
          aria-busy={sharing.pending}
          onClick={sharing.share}
        >
          {common('share.job')}
        </Button>
        {sharing.notice}
      </section>
    );
  }
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <Heading variant="h3" as="h2" id={titleId} className="px-1">
        {t('published.inviteTitle')}
      </Heading>
      <InviteList job={job} shown={INVITES_SHOWN} />
    </section>
  );
}
