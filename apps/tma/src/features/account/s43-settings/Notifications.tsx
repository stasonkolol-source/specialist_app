// Уведомления S43 (DEVELOPMENT_PLAN 4.9, API 2.3a): таблица «группа × канал» — бот (личный чат) и
// приложение (центр уведомлений S42) — и тихие часы. Служебную группу (решения модерации,
// санкции) выключить нельзя — её здесь нет, как на артборде. Нажатие видно сразу, сохранение —
// PUT /me/notification-settings по одному запросу за раз (useUpdateNotificationSettings); ошибка
// возвращает отметку и показывает «Не удалось сохранить». Время тихих часов — по Белграду, в MVP
// не меняется: здесь только включить или выключить.
import type { EventGroup, GroupSettingOut, NotificationSettingsOut } from '@sosed/api-client';
import { useNotificationsGetNotificationSettings } from '@sosed/api-client';
import type { NotificationChannel } from '@sosed/hooks';
import { useUpdateNotificationSettings } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import {
  Banner,
  Button,
  CheckButton,
  Group,
  RowIcon,
  SectionTitle,
  Skeleton,
  SkeletonText,
  Switch,
} from '@sosed/ui-web';
import { useId } from 'react';

const CHANNELS: readonly NotificationChannel[] = ['telegram', 'in_app'];

/** Группы с подписями на S43; служебная `account` не выключается и не показывается. */
type Editable = Exclude<EventGroup, 'account'>;

const isEditable = (row: GroupSettingOut): row is GroupSettingOut & { group: Editable } =>
  !row.mandatory && row.group !== 'account';

/** «22:00:00» → «22:00»: время тихих часов приходит с секундами. */
const hhmm = (time: string) => time.slice(0, 5);

export function Notifications() {
  const { t } = useTranslation('account');
  const titleId = useId();
  const settings = useNotificationsGetNotificationSettings();
  const update = useUpdateNotificationSettings();

  let content;
  if (settings.data) {
    content = (
      <Table
        settings={settings.data}
        onChange={(change) => {
          update.reset();
          update.mutate(change);
        }}
      />
    );
  } else if (settings.isError) {
    content = <LoadError retrying={settings.isFetching} onRetry={() => void settings.refetch()} />;
  } else content = <Loading />;

  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 px-4">
        <SectionTitle id={titleId} inset={false}>
          {t('settings.notifications')}
        </SectionTitle>
        {/* подписи колонок — для глаз: у каждой отметки своя подпись для скринридера */}
        <span aria-hidden="true" className="flex text-cap text-text2">
          {CHANNELS.map((channel) => (
            <span key={channel} className="w-18 text-center">
              {t(`settings.channel.${channel}`)}
            </span>
          ))}
        </span>
      </div>
      {content}
      {update.isError && (
        <Banner tone="danger" role="alert">
          {t('settings.saveError')}
        </Banner>
      )}
    </section>
  );
}

function Table({
  settings,
  onChange,
}: {
  settings: NotificationSettingsOut;
  onChange: ReturnType<typeof useUpdateNotificationSettings>['mutate'];
}) {
  const { t } = useTranslation('account');
  const quietId = useId();
  const quiet = settings.quiet_hours;
  return (
    <Group>
      {settings.groups.filter(isEditable).map((row) => {
        const name = t(`settings.group.${row.group}`);
        return (
          <div
            key={row.group}
            className="flex min-h-13 items-center gap-3 border-b border-line py-1 pr-4 pl-4"
          >
            <span className="min-w-0 flex-1">{name}</span>
            <span className="flex">
              {CHANNELS.map((channel) => (
                <CheckButton
                  key={channel}
                  className="w-18"
                  checked={row[channel]}
                  label={t('settings.groupChannel', { group: name, channel })}
                  onChange={(on) => onChange({ group: row.group, channel, on })}
                />
              ))}
            </span>
          </div>
        );
      })}
      <div className="flex min-h-13 items-center gap-3 px-4 py-3">
        <RowIcon icon="clock" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span id={quietId}>
            {t('settings.quiet', { start: hhmm(quiet.start), end: hhmm(quiet.end) })}
          </span>
          <span className="text-cap text-text2">{t('settings.quietHint')}</span>
        </span>
        <Switch
          checked={quiet.enabled}
          label={t('settings.quiet', { start: hhmm(quiet.start), end: hhmm(quiet.end) })}
          onChange={(on) => onChange({ quiet: on })}
        />
      </div>
    </Group>
  );
}

/** Форма таблицы: пять строк с двумя отметками и строка тихих часов. */
function Loading() {
  const { t } = useTranslation('account');
  return (
    <div role="status">
      <span className="sr-only">{t('settings.loading')}</span>
      <Group>
        <div aria-hidden="true">
          {[0, 1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="flex min-h-13 items-center gap-3 border-b border-line py-1 pr-4 pl-4"
            >
              <SkeletonText className={row % 2 ? 'w-2/5' : 'w-1/2'} />
              <span className="ml-auto flex">
                {CHANNELS.map((channel) => (
                  <span key={channel} className="flex h-11 w-18 items-center justify-center">
                    <Skeleton radius="icon" className="size-5.5" />
                  </span>
                ))}
              </span>
            </div>
          ))}
          <div className="flex min-h-13 items-center gap-3 px-4 py-3">
            <Skeleton radius="icon" className="size-9 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col">
              <SkeletonText className="w-1/2" />
              <SkeletonText size="cap" className="w-2/3" />
            </div>
            <Skeleton round className="h-7.75 w-12.75 shrink-0" />
          </div>
        </div>
      </Group>
    </div>
  );
}

function LoadError({ retrying, onRetry }: { retrying: boolean; onRetry: () => void }) {
  const { t } = useTranslation('account');
  const { t: common } = useTranslation();
  return (
    <Banner tone="danger" role="alert">
      <span className="flex flex-col gap-2">
        <span>{t('settings.loadError')}</span>
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          icon="refresh"
          onClick={onRetry}
          disabled={retrying}
          aria-busy={retrying}
        >
          {common('action.retry')}
        </Button>
      </span>
    </Banner>
  );
}
