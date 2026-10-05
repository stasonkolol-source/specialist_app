// S42 Уведомления (DEVELOPMENT_PLAN 4.9, API 2.3a): лента по курсору, новые сверху, по дням.
// Непрочитанное — с точкой; «Прочитать все» и нажатие на уведомление отмечают прочитанным.
// Нажатие ведёт туда, куда ведёт кнопка в боте (deep link `link`); цели без экрана — на Главную.
// Бот не может писать (канала нет или его остановили) — баннер «Разрешить боту писать».
// «Назад» — нативная кнопка Telegram: на предыдущий экран, без истории — в профиль (S31).
// Шестерёнка в заголовке — настройки уведомлений S43 (4.9).
import type { NotificationOut, NotificationType } from '@sosed/api-client';
import {
  ApiError,
  getNotificationsGetNotificationSettingsQueryKey,
  notificationsGrantTelegramWriteAccess,
  useNotificationsGetNotificationSettings,
} from '@sosed/api-client';
import type { NotificationDay } from '@sosed/hooks';
import {
  feedItems,
  groupByDay,
  systemStateOf,
  unreadCount,
  useMarkNotificationsRead,
  useNotificationFeed,
  useProfileDecisions,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import {
  Banner,
  Button,
  EmptyState,
  FeedRow,
  Group,
  Heading,
  IconButton,
  LinkButton,
  RowIcon,
  RowsSkeleton,
  SectionTitle,
  SkeletonText,
  UnreadDot,
} from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useId } from 'react';

export const NOTIFICATIONS_PATH = '/notifications';
const FALLBACK_PATH = '/profile';
/** Настройки S43 (маршрут фичи account). */
const SETTINGS_PATH = '/settings';

interface Look {
  icon: IconName;
  palette?: AvatarPalette;
  neutral?: boolean;
}

/** Иконка по типу: сделки — акцент, сообщения — синие, отклики и заявки — оранжевые, отзывы —
 *  жёлтые, решения модерации — зелёные, служебное — серое (как на макете S42). */
const LOOK: Record<NotificationType, Look> = {
  'job.matched': { icon: 'jobs', palette: 3 },
  'job.digest': { icon: 'jobs', palette: 3 },
  'job.invited': { icon: 'send', palette: 2 },
  'job.expiring': { icon: 'clock', palette: 3 },
  'job.expired': { icon: 'clock', neutral: true },
  'response.received': { icon: 'jobs', palette: 3 },
  'response.accepted': { icon: 'check-circle' },
  'response.not_selected': { icon: 'jobs', neutral: true },
  'message.received': { icon: 'chat', palette: 2 },
  'deal.proposed': { icon: 'check-circle' },
  'deal.agreed': { icon: 'check-circle' },
  'deal.cancelled': { icon: 'x', neutral: true },
  'deal.reminder': { icon: 'calendar' },
  'deal.completion_prompt': { icon: 'check-circle' },
  'dispute.opened': { icon: 'flag', palette: 3 },
  'dispute.resolved': { icon: 'shield', palette: 1 },
  'review.request': { icon: 'star', palette: 5 },
  'review.published': { icon: 'star', palette: 5 },
  'moderation.decision': { icon: 'shield', palette: 1 },
  'account.restricted': { icon: 'ban', neutral: true },
  'profile.stale_reminder': { icon: 'user', palette: 4 },
  'profile.published': { icon: 'shield', palette: 1 },
  'system.test': { icon: 'bell' },
  // рассылки (2.7b) уходят только в бот; тип — для полноты карты
  broadcast: { icon: 'bell' },
};

export interface NotificationsScreenProps {
  /** Адрес экрана по коду deep link (routes/startapp.ts); `null` — экрана нет. */
  targetOf: (link: string) => string | null;
}

export function NotificationsScreen({ targetOf }: NotificationsScreenProps) {
  const { t } = useTranslation('account');
  const router = useRouter();
  const platform = usePlatform();
  const locale = useLocale();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: FALLBACK_PATH, replace: true });
  });
  // Без initData (браузер) войти нечем: ленту не запрашиваем
  const inTelegram = platform.launch.rawInitData !== null;
  const feed = useNotificationFeed(locale, { enabled: inTelegram });
  const read = useMarkNotificationsRead(locale);
  const signedOut = !inTelegram || (feed.error instanceof ApiError && feed.error.status === 401);
  const items = feedItems(feed.data);
  const unread = unreadCount(feed.data);
  // «Профиль опубликован» здесь, а S31/S33 ещё держат «На проверке» — перечитать профиль (SMOKE-4)
  useProfileDecisions(items);

  let content;
  if (signedOut) content = <SignedOut />;
  else if (feed.data) {
    content =
      items.length === 0 ? (
        <EmptyState icon="bell" title={t('notifications.emptyTitle')} as="h2">
          {t('notifications.emptyText')}
        </EmptyState>
      ) : (
        <>
          {groupByDay(items, new Date()).map((day) => (
            <Day
              key={day.date.getTime()}
              day={day}
              onOpen={(item, event) => {
                event.preventDefault();
                if (!item.read) read.mutate({ ids: [item.id] });
                const target = item.link && targetOf(item.link);
                if (target) void router.navigate({ to: target });
              }}
              hrefOf={(item) => {
                const target = item.link && targetOf(item.link);
                return target ? router.history.createHref(target) : undefined;
              }}
            />
          ))}
          {feed.hasNextPage && (
            <Button
              variant="secondary"
              full
              onClick={() => void feed.fetchNextPage()}
              disabled={feed.isFetchingNextPage}
              aria-busy={feed.isFetchingNextPage}
            >
              {t('notifications.more')}
            </Button>
          )}
          {feed.isFetchNextPageError && (
            <Banner tone="danger" role="alert">
              {t('notifications.moreError')}
            </Banner>
          )}
        </>
      );
  } else if (feed.isError)
    content = <LoadError error={feed.error} onRetry={() => void feed.refetch()} />;
  else content = <Loading />;

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <div className="flex min-h-11 items-center justify-between gap-2">
        <Heading variant="h2" as="h1">
          {t('notifications.title')}
        </Heading>
        <span className="flex items-center gap-1">
          {unread > 0 && (
            <LinkButton onClick={() => read.mutate({ all: true })}>
              {t('notifications.readAll')}
            </LinkButton>
          )}
          {inTelegram && !signedOut && (
            <IconButton
              icon="settings"
              label={t('notifications.settings')}
              href={router.history.createHref(SETTINGS_PATH)}
              onClick={(event) => {
                event.preventDefault();
                void router.navigate({ to: SETTINGS_PATH });
              }}
            />
          )}
        </span>
      </div>
      {read.isError && (
        <Banner tone="danger" role="alert">
          {t('notifications.readError')}
        </Banner>
      )}
      {inTelegram && !signedOut && <BotChannel />}
      {content}
    </section>
  );
}

function Day({
  day,
  onOpen,
  hrefOf,
}: {
  day: NotificationDay;
  onOpen: (item: NotificationOut, event: MouseEvent<HTMLElement>) => void;
  hrefOf: (item: NotificationOut) => string | undefined;
}) {
  const { t } = useTranslation('account');
  const format = useFormat();
  const titleId = useId();
  const now = new Date();
  const title =
    day.key === 'today'
      ? t('notifications.today')
      : day.key === 'yesterday'
        ? t('notifications.yesterday')
        : format.date(day.date, now);
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <SectionTitle>
        <span id={titleId}>{title}</span>
      </SectionTitle>
      <Group>
        {day.items.map((item) => {
          const look = LOOK[item.type];
          const href = hrefOf(item);
          return (
            <FeedRow
              key={item.id}
              title={item.title}
              leading={<RowIcon icon={look.icon} palette={look.palette} neutral={look.neutral} />}
              meta={
                <>
                  {!item.read && <UnreadDot label={t('notifications.unread')} />}
                  {when(new Date(item.created_at), now, day, t, format.time)}
                </>
              }
              {...(href ? { href, onClick: (event) => onOpen(item, event) } : {})}
            >
              {item.body}
            </FeedRow>
          );
        })}
      </Group>
    </section>
  );
}

/** Сегодня — «N мин» в первый час, дальше и в прошлые дни — время: день уже в подзаголовке. */
function when(
  date: Date,
  now: Date,
  day: NotificationDay,
  t: (
    key: 'notifications.justNow' | 'notifications.minutes',
    options?: { count: number },
  ) => string,
  time: (date: Date) => string,
): string {
  if (day.key === 'today') {
    const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
    if (minutes < 1) return t('notifications.justNow');
    if (minutes < 60) return t('notifications.minutes', { count: minutes });
  }
  return time(date);
}

/** Бот не может писать: канала нет или его остановили — предлагаем разрешить (requestWriteAccess
 *  клиента Telegram, затем POST /me/telegram/write-access). Без поддержки в клиенте — только текст. */
function BotChannel() {
  const { t } = useTranslation('account');
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
  if (!settings.data || (channel && channel.writable)) return null;
  return (
    <Banner tone="info" icon="bell">
      <div className="flex flex-col gap-2">
        <span>{t('notifications.botBlocked')}</span>
        {platform.capabilities.requestWriteAccess && (
          <Button
            size="sm"
            className="self-start"
            onClick={() => allow.mutate()}
            disabled={allow.isPending}
            aria-busy={allow.isPending}
          >
            {t('notifications.allowBot')}
          </Button>
        )}
        {allow.isError && <span role="alert">{t('notifications.allowBotFailed')}</span>}
      </div>
    </Banner>
  );
}

function Loading() {
  const { t } = useTranslation('account');
  // live region читает содержимое: текст внутри, скелетоны скрыты (aria-hidden)
  return (
    <div role="status" className="flex flex-col gap-2">
      <span className="sr-only">{t('notifications.loading')}</span>
      <SkeletonText size="cap" screen className="w-24" />
      <RowsSkeleton rows={3} leading="icon" />
    </div>
  );
}

/** Нет сети — S49a «Нет соединения», иначе общая ошибка; обе с «Повторить» и нейтральные, как
 *  остальные LoadError: зелёный — бренд и успех, не ошибка. */
function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation();
  const offline = systemStateOf(error).kind === 'offline';
  return (
    <div role="status">
      <EmptyState
        as="h2"
        icon={offline ? 'wifi-off' : 'alert'}
        tone="neutral"
        title={offline ? t('offline.title') : t('error.title')}
        action={
          <Button variant="secondary" icon="refresh" onClick={onRetry}>
            {t('action.retry')}
          </Button>
        }
      >
        {offline ? t('offline.textEmpty') : t('error.text')}
      </EmptyState>
    </div>
  );
}

function SignedOut() {
  const { t } = useTranslation();
  return (
    <EmptyState as="h2" icon="send" title={t('profile.signedOutTitle')}>
      {t('profile.signedOutText')}
    </EmptyState>
  );
}
