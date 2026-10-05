// S31 Профиль (DEVELOPMENT_PLAN 2.9): имя и город из GET /me, вход в кабинет специалиста, меню.
// Без профиля исполнителя — «Стать специалистом» и «Найти подработку» (мастер S32a–c с отмеченным
// типом); с профилем — карточка со статусом: черновик продолжает мастер с нужного шага, остальное
// ведёт в кабинет S33 (2.10). «Моя активность»: «Сделки и отзывы» S28, «Избранное» S12 (4.6),
// «Уведомления» S42 — число справа — непрочитанные (первая страница ленты S42). «Приложение»:
// «Язык» с текущим языком и «Настройки» ведут в S43 (4.9) — язык, город, уведомления, удаление
// аккаунта. «Поддержка»: «Помощь» S47 и «Правила площадки» S48. Без сети — S49a «Нет соединения»
// вместо ошибки. Пока удаление аккаунта запланировано (S45), сверху — дата и «Отменить».
import type { MeOut, ProfileKind } from '@sosed/api-client';
import { ApiError, useIdentityGetMe } from '@sosed/api-client';
import type { BecomeStep, ProfileState } from '@sosed/hooks';
import {
  becomeStep,
  profileState,
  systemStateOf,
  unreadCount,
  useCancelDeletion,
  useCities,
  useMyProfile,
  useNotificationFeed,
} from '@sosed/hooks';
import { LOCALE_LABELS, useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import type { AvatarPalette, BadgeTone, IconName } from '@sosed/ui-web';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Group,
  Heading,
  Icon,
  Row,
  RowIcon,
  SectionTitle,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent, ReactNode } from 'react';
import { useId } from 'react';

import { ACCOUNT_PATHS, HISTORY_PATH } from '../paths.ts';

/** S48, правила площадки (маршрут features/service/s48-legal). */
const LEGAL_PATH = '/legal/$document';
const RULES_HREF = '/legal/terms';
/** S42, уведомления (маршрут routes/notifications.tsx). */
const NOTIFICATIONS_PATH = '/notifications';
/** S47, помощь (маршрут features/service/s47-help). */
const HELP_PATH = '/help';
/** S12, избранное (маршрут features/catalog). */
const FAVORITES_PATH = '/favorites';
/** Кабинет специалиста S33 (маршрут features/specialist). */
const CABINET_PATH = '/cabinet';
/** Мастер S32a–c (маршруты features/specialist). */
const BECOME_PATHS = {
  type: '/become/type',
  about: '/become/about',
  area: '/become/area',
} as const satisfies Record<BecomeStep, string>;

/** Входы в мастер без профиля: тип отмечен на S32a заранее. Иконки — как на S32a. */
const ENTRIES: readonly { kind: ProfileKind; icon: IconName; palette?: AvatarPalette }[] = [
  { kind: 'pro', icon: 'briefcase' },
  { kind: 'casual', icon: 'clock', palette: 3 },
];

const STATE_TONES: Record<ProfileState, BadgeTone> = {
  draft: 'mute',
  rejected: 'danger',
  pending_review: 'info',
  published: 'ok',
  hidden: 'mute',
  suspended: 'danger',
};

export function AccountScreen() {
  const { t } = useTranslation();
  const platform = usePlatform();
  // Без initData (браузер) войти нечем: /me не запрашиваем
  const inTelegram = platform.launch.rawInitData !== null;
  const me = useIdentityGetMe({ query: { enabled: inTelegram } });
  // 401 приходит, когда mutator уже попробовал войти заново по initData и не смог
  const signedOut = !inTelegram || (me.error instanceof ApiError && me.error.status === 401);

  const retry = () => void me.refetch();
  const offline = me.isError && systemStateOf(me.error).kind === 'offline';

  // Разделы — на постоянных местах: строка уведомлений не пересоздаётся, когда /me загрузился
  let top;
  let account = false;
  if (signedOut) top = <SignedOut />;
  else if (me.data && offline) {
    // S49a: сеть пропала при обновлении — сохранённый профиль виден, но приглушён
    top = (
      <>
        <Offline saved onRetry={retry} retrying={me.isFetching} />
        <Saved at={me.dataUpdatedAt}>
          <AccountHeader me={me.data} />
        </Saved>
      </>
    );
  } else if (me.data) {
    top = (
      <>
        <AccountHeader me={me.data} />
        {me.data.deletion_scheduled_at && (
          <DeletionScheduled at={new Date(me.data.deletion_scheduled_at)} />
        )}
      </>
    );
    account = true;
  } else if (offline) top = <Offline saved={false} onRetry={retry} retrying={me.isFetching} />;
  else if (me.isError) top = <LoadError onRetry={retry} />;
  else top = <Loading />;

  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6">
      {/* заголовок экрана — для скринридера: на артборде сверху сразу аватар и имя */}
      <Heading variant="h1" className="sr-only">
        {t('nav.profile')}
      </Heading>
      {top}
      {account && <Specialist />}
      {!signedOut && <Activity />}
      {!signedOut && <AppSettings />}
      <Support />
    </section>
  );
}

/**
 * Вход в кабинет специалиста. Профиля нет — «Стать специалистом» и «Найти подработку»; есть —
 * карточка со статусом. Не загрузился — раздела нет: остальной профиль работает и без него.
 */
function Specialist() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  if (profile.isPending) {
    return (
      <SkeletonCard className="min-h-21 flex-row items-center">
        <Skeleton radius="icon" className="size-11 shrink-0" />
        <div className="flex min-w-0 grow flex-col">
          <SkeletonText size="title" className="w-1/2" />
          <SkeletonText size="cap" className="w-2/3" />
        </div>
      </SkeletonCard>
    );
  }
  if (profile.isError) return null;

  const go = (event: MouseEvent<HTMLElement>, step: BecomeStep, kind?: ProfileKind) => {
    event.preventDefault();
    void router.navigate({ to: BECOME_PATHS[step], search: kind ? { kind } : {} });
  };

  if (profile.data === null) {
    return (
      <Group>
        {ENTRIES.map((entry) => (
          <Row
            key={entry.kind}
            leading={<RowIcon icon={entry.icon} palette={entry.palette} />}
            title={t(`account.${entry.kind}.title`)}
            subtitle={t(`account.${entry.kind}.text`)}
            chevron
            href={router.history.createHref(`${BECOME_PATHS.type}?kind=${entry.kind}`)}
            onClick={(event) => go(event, 'type', entry.kind)}
          />
        ))}
      </Group>
    );
  }

  const state = profileState(profile.data);
  // черновик — дописать в мастере с нужного шага, остальное — в кабинет S33
  const step = becomeStep(profile.data);
  const target = step ? BECOME_PATHS[step] : CABINET_PATH;
  const openCabinet = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: target });
  };
  return (
    <Card href={router.history.createHref(target)} onClick={openCabinet}>
      <span className="flex items-center gap-3">
        <RowIcon icon="briefcase" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-semibold">
            {t(profile.data.kind === 'pro' ? 'account.cabinet' : 'account.casualCabinet')}
          </span>
          <Text as="span" variant="cap">
            {t(`account.status.${state}.text`)}
          </Text>
        </span>
        <Icon name="chev-right" className="text-text2" />
      </span>
      <span className="flex flex-wrap gap-1.5">
        <Badge tone={STATE_TONES[state]}>{t(`account.status.${state}.label`)}</Badge>
      </span>
    </Card>
  );
}

/** «Моя активность»: сделки и отзывы S28, избранное S12, уведомления S42. */
function Activity() {
  const { t } = useTranslation();
  const { t: ts } = useTranslation('account');
  const router = useRouter();
  const feed = useNotificationFeed(useLocale());
  const unread = unreadCount(feed.data);
  const open = (to: string) => (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to });
  };
  return (
    <nav aria-label={t('profile.activity')}>
      <Group>
        {/* история, как на артборде: briefcase уже у «Стать специалистом» */}
        <Row
          icon="history"
          title={t('profile.history')}
          chevron
          href={router.history.createHref(HISTORY_PATH)}
          onClick={open(HISTORY_PATH)}
        />
        <Row
          icon="heart"
          title={t('profile.favorites')}
          chevron
          href={router.history.createHref(FAVORITES_PATH)}
          onClick={open(FAVORITES_PATH)}
        />
        <Row
          icon="bell"
          title={t('settings.notifications')}
          trailing={
            unread > 0 && (
              <Badge tone="ok">
                <span aria-hidden="true">{unread}</span>
                <span className="sr-only">
                  {ts('notifications.unreadCount', { count: unread })}
                </span>
              </Badge>
            )
          }
          chevron
          href={router.history.createHref(NOTIFICATIONS_PATH)}
          onClick={open(NOTIFICATIONS_PATH)}
        />
      </Group>
    </nav>
  );
}

/** «Приложение»: язык с текущим выбором и остальные настройки — оба ведут в S43. */
function AppSettings() {
  const { t } = useTranslation();
  const { t: ts } = useTranslation('account');
  const router = useRouter();
  const locale = useLocale();
  const open = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: ACCOUNT_PATHS.settings });
  };
  const href = router.history.createHref(ACCOUNT_PATHS.settings);
  return (
    <nav aria-label={ts('settings.app')}>
      <Group>
        <Row
          icon="languages"
          title={t('settings.language')}
          trailing={
            <Text as="span" secondary>
              <span lang={locale}>{LOCALE_LABELS[locale].name}</span>
            </Text>
          }
          chevron
          href={href}
          onClick={open}
        />
        <Row icon="settings" title={t('settings.title')} chevron href={href} onClick={open} />
      </Group>
    </nav>
  );
}

/** «Поддержка»: помощь S47 и правила площадки S48. */
function Support() {
  const { t } = useTranslation();
  const { t: ts } = useTranslation('account');
  const router = useRouter();
  const openHelp = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: HELP_PATH });
  };
  const openRules = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: LEGAL_PATH, params: { document: 'terms' } });
  };
  return (
    <nav aria-label={t('profile.support')}>
      <Group>
        <Row
          icon="help"
          title={ts('help.title')}
          chevron
          href={router.history.createHref(HELP_PATH)}
          onClick={openHelp}
        />
        <Row
          icon="file"
          title={t('profile.rules')}
          chevron
          href={router.history.createHref(RULES_HREF)}
          onClick={openRules}
        />
      </Group>
    </nav>
  );
}

/** Удаление запланировано (S45): дата и «Отменить» — передумавшему не нужно искать экран. */
function DeletionScheduled({ at }: { at: Date }) {
  const { t } = useTranslation('account');
  const format = useFormat();
  const platform = usePlatform();
  const cancel = useCancelDeletion();
  return (
    <Banner tone="danger" role="status">
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">
          {t('deletion.scheduled', { date: format.dateGenitive(at) })}
        </span>
        <button
          type="button"
          disabled={cancel.isPending}
          onClick={() =>
            cancel.mutate(undefined, {
              onSuccess: () => platform.haptics.notification('success'),
            })
          }
          className="min-h-11 border-0 bg-transparent p-0 font-semibold text-inherit underline"
        >
          {t('deletion.cancelShort')}
        </button>
      </span>
    </Banner>
  );
}

/** S49a: нет сети. С сохранёнными данными — текст макета, без них — просьба проверить сеть. */
function Offline({
  saved,
  onRetry,
  retrying,
}: {
  saved: boolean;
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div role="status">
      <EmptyState
        as="h2"
        size="h2"
        tone="neutral"
        icon="wifi-off"
        title={t('offline.title')}
        className="px-6 pt-2"
        action={
          <Button
            variant="secondary"
            icon="refresh"
            onClick={onRetry}
            disabled={retrying}
            aria-busy={retrying}
          >
            {t('action.retry')}
          </Button>
        }
      >
        {saved ? t('offline.text') : t('offline.textEmpty')}
      </EmptyState>
    </div>
  );
}

/** Сохранённое до обрыва сети: приглушено, с временем последнего обновления. */
function Saved({ at, children }: { at: number; children: ReactNode }) {
  const { t } = useTranslation();
  const format = useFormat();
  const titleId = useId();
  return (
    // приглушено, как на артборде S49a (opacity .55): контраст ниже AA — это устаревшие данные, а
    // не текст для чтения; e2e исключает [data-stale] из проверки контраста axe
    <section aria-labelledby={titleId} data-stale className="flex flex-col gap-2 opacity-55">
      <SectionTitle>
        <span id={titleId}>{t('offline.saved', { time: format.time(new Date(at)) })}</span>
      </SectionTitle>
      {children}
    </section>
  );
}

/** Аватар, имя и город, как на артборде S31. */
function AccountHeader({ me }: { me: MeOut }) {
  const cities = useCities(useLocale());
  const city = cities.data?.find((candidate) => candidate.id === me.home_city_id);
  return (
    <div className="flex items-center gap-4 px-1 pt-1">
      {/* имя рядом — аватар для скринридера лишний */}
      <span aria-hidden="true">
        <Avatar name={me.display_name} size="lg" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Heading variant="h2" as="h2">
          {me.display_name}
        </Heading>
        {city && (
          <Text as="span" variant="cap" className="flex items-center gap-1.5">
            <Icon name="pin" size={16} />
            {city.name}
          </Text>
        )}
      </div>
    </div>
  );
}

function Loading() {
  const { t } = useTranslation();
  // live region читает содержимое, а не aria-label: текст — внутри, скелетоны скрыты (aria-hidden)
  return (
    <div role="status" className="flex items-center gap-4">
      <span className="sr-only">{t('profile.loading')}</span>
      <Skeleton round screen className="size-22" />
      <div className="flex flex-1 flex-col gap-2">
        <Skeleton screen className="h-6 w-2/3" />
        <Skeleton screen className="h-4 w-1/2" />
      </div>
    </div>
  );
}

function LoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <EmptyState
      as="h2"
      icon="alert"
      title={t('error.title')}
      action={
        <Button variant="secondary" onClick={onRetry}>
          {t('action.retry')}
        </Button>
      }
    >
      {t('error.text')}
    </EmptyState>
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
