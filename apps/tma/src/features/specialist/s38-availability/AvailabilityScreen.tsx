// S38 Доступность (DEVELOPMENT_PLAN 2.10): «Доступен сегодня» с вариантами «до 18:00 / 20:00 /
// 22:00» (прошедшие — недоступны) → PUT /me/profile/availability; «Пауза или отпуск» скрывает
// опубликованный профиль (POST /me/profile/hide, /show). Сохраняется по MainButton, только
// изменённое. Расписание на неделю с артборда — v1.
import type { ProfileOut } from '@sosed/api-client';
import { specialistsHideMyProfile, specialistsShowMyProfile } from '@sosed/api-client';
import type { AvailabilityHour } from '@sosed/domain';
import {
  AVAILABILITY_HOURS,
  availabilityHour,
  availableUntil,
  isUpcoming,
  quickHour,
  untilTime,
} from '@sosed/domain';
import { useMyProfile, useSetAvailability } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Card, Chip, Chips, Heading, Switch, Text } from '@sosed/ui-web';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import { useEffect, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useBecomeFlow, useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';

export function AvailabilityScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  const back = () => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.home, replace: true });
  };
  useBackButton(back);
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data) return <AvailabilityForm profile={profile.data} onSaved={back} />;
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('availability.title')}
      </Heading>
      <LoadState
        shape="availability"
        error={profile.isError ? profile.error : null}
        onRetry={() => void profile.refetch()}
        retrying={profile.isFetching}
      />
    </section>
  );
}

function AvailabilityForm({ profile, onSaved }: { profile: ProfileOut; onSaved: () => void }) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  const flow = useBecomeFlow();
  const setAvailability = useSetAvailability();
  const now = new Date();
  const until = availableUntil(profile.available_until, now);
  const late = quickHour(now) === null;
  const [on, setOn] = useState(until !== null);
  const [hour, setHour] = useState<AvailabilityHour | null>(
    () => availabilityHour(until) ?? quickHour(new Date()),
  );
  const pausable = profile.status === 'published' || profile.status === 'hidden';
  const [paused, setPaused] = useState(profile.status === 'hidden');

  const save = useMutation({
    mutationFn: async () => {
      const wanted = on ? hour : null;
      const current = until === null ? null : availabilityHour(until);
      // свой срок из бота («до 19:30») без правок не трогаем
      const touched = on !== (until !== null) || (on && wanted !== current);
      if (touched && (wanted === null || isUpcoming(wanted, new Date()))) {
        await setAvailability.mutateAsync(wanted);
      }
      if (pausable && paused !== (profile.status === 'hidden')) {
        flow.saved(await (paused ? specialistsHideMyProfile() : specialistsShowMyProfile()));
      }
    },
    onSuccess: () => {
      platform.haptics.notification('success');
      onSaved();
    },
  });
  useStepButton({
    text: t('availability.save'),
    onClick: () => {
      if (!save.isPending) save.mutate();
    },
    loading: save.isPending,
  });

  const toggle = (next: boolean) => {
    platform.haptics.selection();
    setOn(next);
    if (next && (hour === null || !isUpcoming(hour, new Date()))) setHour(quickHour(new Date()));
  };
  const choose = (next: AvailabilityHour) => {
    platform.haptics.selection();
    setHour(next);
    setOn(true);
  };
  const shown = on && hour !== null ? untilTime(hour) : null;

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('availability.title')}
      </Heading>
      <Card as="section">
        <div className="flex items-center gap-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <Text bold>{t('availability.today')}</Text>
            <Text variant="cap">
              {shown
                ? t('availability.todayOn', { time: shown })
                : late
                  ? t('availability.todayLate')
                  : t('availability.todayOff')}
            </Text>
          </div>
          <Switch
            checked={on}
            onChange={toggle}
            label={t('availability.today')}
            disabled={late && !on}
          />
        </div>
        <Chips wrap label={t('availability.options')}>
          {AVAILABILITY_HOURS.map((option) => (
            <Chip
              key={option}
              selected={on && hour === option}
              disabled={!isUpcoming(option, now)}
              onClick={() => choose(option)}
            >
              {t('availability.until', { time: untilTime(option) })}
            </Chip>
          ))}
        </Chips>
      </Card>
      <Card as="section">
        <div className="flex items-center gap-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <Text bold>{t('availability.pause')}</Text>
            <Text variant="cap">
              {pausable ? t('availability.pauseText') : t('availability.pauseUnavailable')}
            </Text>
          </div>
          <Switch
            checked={paused}
            onChange={(next) => {
              platform.haptics.selection();
              setPaused(next);
            }}
            label={t('availability.pause')}
            disabled={!pausable}
          />
        </div>
      </Card>
      {save.isError && <SaveError error={save.error} />}
    </section>
  );
}
