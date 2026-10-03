// S18 Подписки на заявки (DEVELOPMENT_PLAN 5.7): «присылай заявки по электрике в Лимане от 3 000
// RSD». Карточка подписки — название по первой категории и подпись, переключатель «присылать»,
// где и от какого бюджета, «сразу» или «подборкой в 09:00» (час дайджеста — из настроек
// уведомлений), пауза из бота, «N заявок за неделю», «Изменить» (S19) и «Удалить» с
// подтверждением. Тихие часы — строкой со ссылкой на настройки S43. Если боту нельзя писать —
// «Присылать новые заявки в бот?» (requestWriteAccess): без него подписки молчат. MainButton —
// «Новая подписка» (S19); одиннадцатая — «удалите одну» (сервер ответил бы 409 `job_alerts_full`).
// Вход — колокольчик ленты S13, кнопки бота «Пауза подписки» и `/alerts` (`m_alerts`).
import type { CategoryOut, DistrictOut, JobAlertOut } from '@sosed/api-client';
import { useNotificationsGetNotificationSettings } from '@sosed/api-client';
import {
  ALERTS_MAX,
  nearestDistrict,
  receives,
  useCategories,
  useDeleteAlert,
  useDistricts,
  useJobAlerts,
  useUpdateAlert,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import {
  Banner,
  Button,
  Card,
  EmptyState,
  Heading,
  Icon,
  LinkButton,
  RowIcon,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Switch,
  Text,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent, ReactNode } from 'react';
import { useId, useState } from 'react';

import { BotChannel } from '../shared/BotChannel.tsx';
import { LoadError } from '../shared/LoadError.tsx';
import { alertName, isFeedLanguage } from '../shared/alerts.ts';
import { useStepButton } from '../shared/flow.ts';
import { JOBS_PATHS, SETTINGS_PATH, alertPath } from '../shared/paths.ts';

const DIGEST_HOUR = 9;
const PALETTES: readonly AvatarPalette[] = [1, 3, 2, 4, 5];

export function AlertsScreen() {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const router = useRouter();
  const alerts = useJobAlerts();
  const settings = useNotificationsGetNotificationSettings();
  const tree = useCategories(locale).data ?? [];
  const items = alerts.data?.items ?? [];
  const cityId = items.find((item) => item.criteria.center)?.criteria.city_id ?? null;
  const districts = useDistricts(cityId, locale).data ?? [];
  const [fullShown, setFullShown] = useState(false);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.feed, replace: true });
  });

  const limit = alerts.data?.limit ?? ALERTS_MAX;
  const full = items.length >= limit;
  const digestHour = settings.data?.digest_hour ?? DIGEST_HOUR;
  const quiet = settings.data?.quiet_hours;

  let content: ReactNode;
  if (alerts.isError) {
    content = (
      <LoadError
        error={alerts.error}
        onRetry={() => void alerts.refetch()}
        retrying={alerts.isRefetching}
      />
    );
  } else if (!alerts.data) {
    content = (
      <>
        <AlertSkeleton />
        <AlertSkeleton />
      </>
    );
  } else if (items.length === 0) {
    content = (
      <EmptyState as="h2" icon="bell" title={t('alerts.emptyTitle')}>
        {t('alerts.emptyText')}
      </EmptyState>
    );
  } else {
    content = items.map((alert, index) => (
      <AlertCard
        key={alert.id}
        alert={alert}
        tree={tree}
        districts={districts}
        palette={PALETTES[index % PALETTES.length] ?? 1}
        digestHour={digestHour}
        onEdit={() => void router.navigate({ to: alertPath(alert.id) })}
      />
    ));
  }

  const toSettings = (event: MouseEvent) => {
    event.preventDefault();
    void router.navigate({ to: SETTINGS_PATH });
  };
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {t('alerts.title')}
        </Heading>
        <Text variant="cap">{t('alerts.lead')}</Text>
      </div>
      <BotChannel
        texts={{
          title: t('alerts.botTitle'),
          text: t('alerts.botText'),
          allow: t('alerts.botAllow'),
          on: t('alerts.botOn'),
          denied: t('alerts.botDenied'),
        }}
      />
      {fullShown && full && (
        <Banner tone="warn" role="alert">
          {t('alerts.full', { limit })}
        </Banner>
      )}
      {content}
      {quiet?.enabled && items.length > 0 && (
        <Banner tone="info" icon="clock">
          {t('alerts.quiet', { from: quiet.start.slice(0, 5), to: quiet.end.slice(0, 5) })}{' '}
          <a href={SETTINGS_PATH} onClick={toSettings}>
            {t('alerts.quietLink')}
          </a>
        </Banner>
      )}
      {alerts.data && (
        <NewButton
          onClick={() =>
            full ? setFullShown(true) : void router.navigate({ to: JOBS_PATHS.newAlert })
          }
        />
      )}
    </section>
  );
}

function NewButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation('jobs');
  useStepButton({ text: t('alerts.new'), onClick });
  return null;
}

/** Подписка, пока не пришла: иконка, название с подписью, переключатель, две строки, итог. */
function AlertSkeleton() {
  return (
    <SkeletonCard>
      <div className="flex items-center gap-3">
        <Skeleton radius="icon" className="size-9" />
        <div className="flex flex-1 flex-col gap-1">
          <SkeletonText size="title" className="w-1/2" />
          <SkeletonText size="cap" className="w-3/4" />
        </div>
        <Skeleton round className="h-7.75 w-12.75" />
      </div>
      <SkeletonText size="cap" className="w-4/5" />
      <SkeletonText size="cap" className="w-2/5" />
    </SkeletonCard>
  );
}

function AlertCard({
  alert,
  tree,
  districts,
  palette,
  digestHour,
  onEdit,
}: {
  alert: JobAlertOut;
  tree: readonly CategoryOut[];
  districts: readonly DistrictOut[];
  palette: AvatarPalette;
  digestHour: number;
  onEdit: () => void;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const platform = usePlatform();
  const update = useUpdateAlert();
  const remove = useDeleteAlert();
  const titleId = useId();
  const name = alertName(tree, alert.criteria.category_ids, (title, count) =>
    t('alerts.more', { title, count }),
  );
  const title = name?.title ?? t('alerts.title');
  const on = receives(alert);
  const paused = alert.is_active && !on && alert.paused_until !== null;
  const failed = update.isError || remove.isError;
  const area = useAreaLine(alert, districts);

  const drop = async () => {
    if (!(await platform.confirm(t('alerts.deleteConfirm', { title })))) return;
    remove.mutate(alert.id);
  };
  return (
    <Card as="section" aria-labelledby={titleId}>
      <div className="flex items-center gap-3">
        <RowIcon icon={name?.icon ?? 'bell'} palette={palette} />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span id={titleId} className="truncate font-semibold">
            {title}
          </span>
          {name?.caption && <span className="truncate text-cap text-text2">{name.caption}</span>}
        </span>
        <Switch
          checked={on}
          label={t('alerts.toggle', { title })}
          onChange={(checked) =>
            update.mutate({ alertId: alert.id, body: { is_active: checked } })
          }
        />
      </div>
      <div className="flex flex-col gap-1">
        <Meta icon="pin">{area}</Meta>
        {paused && alert.paused_until ? (
          <Meta icon="clock">
            {t('alerts.paused', { date: format.calendar(new Date(alert.paused_until)) })}
          </Meta>
        ) : alert.delivery === 'digest' ? (
          <Meta icon="calendar">
            {t('alerts.digest', { time: `${String(digestHour).padStart(2, '0')}:00` })}
          </Meta>
        ) : (
          <Meta icon="zap">{t('alerts.instant')}</Meta>
        )}
      </div>
      {failed && (
        <Text variant="cap" className="text-danger" role="alert">
          {t('alerts.error')}
        </Text>
      )}
      <div className="border-t border-line" aria-hidden="true" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Meta icon="chart">{t('alerts.week', { count: alert.week_count })}</Meta>
        <span className="flex items-center gap-1">
          <Button variant="outline" size="sm" aria-describedby={titleId} onClick={onEdit}>
            {t('alerts.edit')}
          </Button>
          <LinkButton
            danger
            aria-describedby={titleId}
            disabled={remove.isPending}
            onClick={() => void drop()}
          >
            {t('alerts.delete')}
          </LinkButton>
        </span>
      </div>
    </Card>
  );
}

/** «До 3 км · Лиман · от 2 000 RSD · русский»: где, бюджет, язык и «только срочные». */
function useAreaLine(alert: JobAlertOut, districts: readonly DistrictOut[]): string {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const { criteria } = alert;
  const near = criteria.center ? nearestDistrict(districts, criteria.center) : null;
  const where = criteria.center
    ? near
      ? t('alerts.radiusFrom', { km: criteria.radius_km ?? 0, place: near.name })
      : t('alerts.radius', { km: criteria.radius_km ?? 0 })
    : criteria.district_ids.length > 0
      ? criteria.district_ids
          .map((id) => districts.find((district) => district.id === id)?.name)
          .filter(Boolean)
          .join(', ') || t('alerts.city')
      : t('alerts.city');
  const budget =
    criteria.min_budget !== null
      ? t('alerts.budgetFrom', { amount: format.money(criteria.min_budget) })
      : t('alerts.anyBudget');
  const languages =
    criteria.languages.length > 0
      ? criteria.languages
          .map((code) => (isFeedLanguage(code) ? t(`create.budget.langs.${code}`) : code))
          .join(', ')
      : t('alerts.anyLanguage');
  const urgent =
    criteria.urgencies.length === 1 && criteria.urgencies[0] === 'asap'
      ? [t('alerts.urgentOnly')]
      : [];
  return [where, budget, languages.toLowerCase(), ...urgent].join(' · ');
}

function Meta({ icon, children }: { icon: IconName; children: ReactNode }) {
  return (
    <p className="m-0 flex min-w-0 items-center gap-1.5 text-cap text-text2">
      <Icon name={icon} size={16} className="shrink-0" />
      <span>{children}</span>
    </p>
  );
}
