// S33 Кабинет специалиста (DEVELOPMENT_PLAN 2.10): статус профиля, полнота с первой подсказкой,
// «Доступен сегодня до …» (переключатель: включает «до 20:00» или ближайший вариант, подробно — S38)
// и переходы к правке S34, прайсу S35 и доступности S38. Черновик и «нужны правки» продолжают
// мастер S32 с нужного шага (MainButton). Блоки артборда, чьих экранов ещё нет, появятся со своими
// шагами: портфолио — 2.11, «Посмотреть как клиент» — 4.5; «За 30 дней» и «Скоро» — v1.
import type { HintOut, ProfileOut } from '@sosed/api-client';
import { usePricingListMyServices } from '@sosed/api-client';
import { availableUntil, quickHour } from '@sosed/domain';
import type { ProfileState } from '@sosed/hooks';
import { becomeStep, profileState, useMyProfile, useSetAvailability } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { IconName } from '@sosed/ui-web';
import { Card, Group, Heading, Icon, ProgressBar, Row, Switch, Text, cx } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useBecomeFlow, useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';

const STATE_ICONS: Record<ProfileState, { icon: IconName; tone: string }> = {
  published: { icon: 'check-circle', tone: 'text-accent' },
  pending_review: { icon: 'clock', tone: 'text-info-ink' },
  draft: { icon: 'edit', tone: 'text-text2' },
  rejected: { icon: 'alert', tone: 'text-danger' },
  hidden: { icon: 'eye', tone: 'text-text2' },
  suspended: { icon: 'ban', tone: 'text-danger' },
};

export function CabinetScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATH, replace: true });
  });
  // профиля нет (кабинет открыли по ссылке) — вход в мастер на S31
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data) return <Cabinet profile={profile.data} />;
  return (
    <section className="flex flex-col gap-3 px-4 pt-2 pb-6">
      <Heading variant="h2" as="h1">
        {t('cabinet.title')}
      </Heading>
      <LoadState
        error={profile.isError ? profile.error : null}
        onRetry={() => void profile.refetch()}
        retrying={profile.isFetching}
      />
    </section>
  );
}

function Cabinet({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const flow = useBecomeFlow();
  const state = profileState(profile);
  const step = becomeStep(profile);
  const { icon, tone } = STATE_ICONS[state];
  const stateText =
    state === 'published' && !profile.listed_in_catalog ? 'publishedUnlisted' : state;
  const { percent, hints } = profile.completeness;

  // черновик — дописать в мастере; MainButton — главное действие экрана, как в Telegram
  useStepButton({
    text: t(state === 'rejected' ? 'cabinet.fix' : 'cabinet.continue'),
    onClick: () => step && flow.open(step),
    visible: step !== null,
  });

  const open =
    (to: (typeof CABINET_PATHS)['profile' | 'availability' | 'prices']) =>
    (event: MouseEvent<HTMLElement>) => {
      event.preventDefault();
      void router.navigate({ to });
    };
  // доступность и пауза — у профиля, который видят клиенты
  const visible = profile.status === 'published' || profile.status === 'hidden';

  return (
    <section className="flex flex-col gap-2.5 px-4 pt-2 pb-6">
      <Card as="section">
        <div className="flex flex-col gap-1">
          <Heading variant="h2" as="h1">
            {t(profile.kind === 'pro' ? 'cabinet.title' : 'cabinet.casualTitle')}
          </Heading>
          <Text variant="sm" className="flex items-center gap-1.5">
            <Icon name={icon} size={16} className={tone} />
            {t(`cabinet.state.${stateText}`)}
          </Text>
        </div>
        <div className="flex flex-col gap-2">
          <Text variant="sm" bold>
            {t('cabinet.filled', { percent })}
          </Text>
          <ProgressBar value={percent} label={t('cabinet.filledLabel')} />
          <Text variant="cap">
            {hints[0] ? <HintText hint={hints[0]} /> : t('cabinet.complete')}
          </Text>
        </div>
        {profile.status === 'published' && <AvailableToday profile={profile} />}
      </Card>
      <nav aria-label={t('cabinet.manage')}>
        <Group>
          <Row
            icon="user"
            title={t('cabinet.profile')}
            chevron
            href={router.history.createHref(CABINET_PATHS.profile)}
            onClick={open(CABINET_PATHS.profile)}
          />
          <Row
            icon="list"
            title={t('cabinet.prices')}
            trailing={<PriceCount />}
            chevron
            href={router.history.createHref(CABINET_PATHS.prices)}
            onClick={open(CABINET_PATHS.prices)}
          />
          {visible && (
            <Row
              icon="calendar"
              title={t('cabinet.availability')}
              trailing={<AvailabilityValue profile={profile} />}
              chevron
              href={router.history.createHref(CABINET_PATHS.availability)}
              onClick={open(CABINET_PATHS.availability)}
            />
          )}
        </Group>
      </nav>
    </section>
  );
}

const HINT_CODES = [
  'category_ids',
  'headline',
  'about',
  'languages',
  'area_ids',
  'services',
  'service_descriptions',
] as const;

/** Подсказка полноты по коду сервера; незнакомый код (новый backend) — без подсказки. */
function HintText({ hint }: { hint: HintOut }) {
  const { t } = useTranslation('specialist');
  const code = HINT_CODES.find((known) => known === hint.code);
  if (!code) return null;
  return (
    <span className={cx(code === 'service_descriptions' && 'tabular-nums')}>
      {t(`cabinet.hint.${code}`, { count: hint.count ?? 0 })}
    </span>
  );
}

/** «Доступен сегодня до …» в карточке: переключатель включает «до 20:00» или ближайший вариант. */
function AvailableToday({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const format = useFormat();
  const platform = usePlatform();
  const setAvailability = useSetAvailability();
  const now = new Date();
  const until = availableUntil(profile.available_until, now);
  const quick = quickHour(now);
  const toggle = (on: boolean) => {
    platform.haptics.selection();
    setAvailability.mutate(on ? quick : null);
  };
  const label = until
    ? t('cabinet.availableUntil', { time: format.time(until) })
    : t('cabinet.availableToday');
  return (
    <>
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 text-body">{label}</span>
        <Switch
          checked={until !== null}
          onChange={toggle}
          label={label}
          disabled={setAvailability.isPending || (until === null && quick === null)}
        />
      </div>
      {until === null && quick === null && <Text variant="cap">{t('availability.todayLate')}</Text>}
      {setAvailability.isError && <SaveError error={setAvailability.error} />}
    </>
  );
}

/** Значение строки «Доступность»: «сегодня до 20:00» или «выключено». */
function AvailabilityValue({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const format = useFormat();
  const until = availableUntil(profile.available_until, new Date());
  return (
    <Text as="span" variant="sm" secondary>
      {until
        ? t('cabinet.availabilityValue', { time: format.time(until) })
        : t('cabinet.availabilityOff')}
    </Text>
  );
}

/** Сколько позиций в прайсе — справа в строке «Прайс», как на артборде. */
function PriceCount() {
  const services = usePricingListMyServices();
  const count = services.data?.items.length;
  if (!count) return null;
  return (
    <Text as="span" variant="sm" secondary>
      {count}
    </Text>
  );
}
