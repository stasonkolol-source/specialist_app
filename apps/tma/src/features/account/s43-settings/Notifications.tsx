// Уведомления S43 (DEVELOPMENT_PLAN 4.9, API 2.3a): таблица «группа × канал» — бот (личный чат) и
// приложение (центр уведомлений S42) — и тихие часы. Служебную группу (решения модерации,
// санкции) выключить нельзя — её здесь нет, как на артборде. Нажатие видно сразу, сохранение —
// PUT /me/notification-settings по одному запросу за раз (useUpdateNotificationSettings); ошибка
// возвращает отметку и показывает «Не удалось сохранить». Время тихих часов — по Белграду, в MVP
// не меняется: здесь только включить или выключить. «Запуск раздела «Вещи»» (`goods_launch`, 7.5) —
// не отметки по каналам, а один переключатель: подписывает кнопка S58, здесь — отписка. Строка
// видна подписанным и не пропадает, пока человек на экране: выключил по ошибке — включит обратно.
// Колонки каналов — по ширине своих подписей, а не 72 px артборда: на 360 px те переносили
// названия групп («Dogovori, sporovi, utisci»).
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
  cx,
} from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { useId, useState } from 'react';

const CHANNELS: readonly NotificationChannel[] = ['telegram', 'in_app'];

/** Группы с отметками на S43; служебная `account` не выключается и не показывается, у
 *  `goods_launch` — свой переключатель. */
type Editable = Exclude<EventGroup, 'account' | 'goods_launch'>;

const isEditable = (row: GroupSettingOut): row is GroupSettingOut & { group: Editable } =>
  !row.mandatory && row.group !== 'account' && row.group !== 'goods_launch';

/** «22:00:00» → «22:00»: время тихих часов приходит с секундами. */
const hhmm = (time: string) => time.slice(0, 5);

/** Ячейка колонки канала: ширина — по подписи шапки («Бот», «Приложение»), но не уже 44 px
 *  касания. В строках подпись лежит невидимой и нулевой высоты — колонки шапки и строк совпадают
 *  на любом языке. Без содержимого — сама подпись (шапка). */
function Column({ channel, children }: { channel: NotificationChannel; children?: ReactNode }) {
  const { t } = useTranslation('account');
  return (
    <span className="grid min-w-11 text-center">
      <span
        className={cx(
          'col-start-1 row-start-1 text-cap whitespace-nowrap',
          children ? 'invisible h-0' : 'text-text2',
        )}
      >
        {t(`settings.channel.${channel}`)}
      </span>
      {children}
    </span>
  );
}

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
        <span aria-hidden="true" className="flex">
          {CHANNELS.map((channel) => (
            <Column key={channel} channel={channel} />
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
  const goodsId = useId();
  const quiet = settings.quiet_hours;
  const goods = settings.groups.find((row) => row.group === 'goods_launch');
  const waiting = goods !== undefined && (goods.telegram || goods.in_app);
  const [goodsShown, setGoodsShown] = useState(waiting);
  if (waiting && !goodsShown) setGoodsShown(true);
  return (
    <Group>
      {settings.groups.filter(isEditable).map((row) => {
        const name = t(`settings.group.${row.group}`);
        return (
          // до колонок — 4 px: у отметки в колонке и так поля по 11 px и больше
          <div
            key={row.group}
            className="flex min-h-13 items-center gap-1 border-b border-line py-1 pr-4 pl-4"
          >
            <span className="min-w-0 flex-1">{name}</span>
            <span className="flex">
              {CHANNELS.map((channel) => (
                <Column key={channel} channel={channel}>
                  <CheckButton
                    className="col-start-1 row-start-1"
                    checked={row[channel]}
                    label={t('settings.groupChannel', { group: name, channel })}
                    onChange={(on) => onChange({ group: row.group, channel, on })}
                  />
                </Column>
              ))}
            </span>
          </div>
        );
      })}
      {goodsShown && (
        <div className="flex min-h-13 items-center gap-3 border-b border-line px-4 py-3">
          <RowIcon icon="bag" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span id={goodsId}>{t('settings.goodsLaunch')}</span>
            <span className="text-cap text-text2">{t('settings.goodsLaunchHint')}</span>
          </span>
          <Switch
            checked={waiting}
            label={t('settings.goodsLaunch')}
            onChange={(on) => onChange({ group: 'goods_launch', on })}
          />
        </div>
      )}
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
              className="flex min-h-13 items-center gap-1 border-b border-line py-1 pr-4 pl-4"
            >
              <SkeletonText className={row % 2 ? 'w-2/5' : 'w-1/2'} />
              <span className="ml-auto flex">
                {CHANNELS.map((channel) => (
                  <Column key={channel} channel={channel}>
                    <span className="col-start-1 row-start-1 flex h-11 items-center justify-center">
                      <Skeleton radius="icon" className="size-5.5" />
                    </span>
                  </Column>
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
