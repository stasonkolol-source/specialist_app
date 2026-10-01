// S32a «Как вы хотите работать?», шаг 1 из 3 (DEVELOPMENT_PLAN 2.9): тип профиля. Профиля ещё
// нет — POST /me/profile {kind, city_id} создаёт черновик в городе из онбординга; черновик уже
// есть — PATCH меняет его тип. Отмечен тип из адреса (S31: «Стать специалистом» или «Найти
// подработку»), иначе «Специалист», как на артборде.
import type { ProfileKind, ProfileOut } from '@sosed/api-client';
import {
  ApiError,
  useIdentityGetMe,
  useSpecialistsCreateMyProfile,
  useSpecialistsUpdateMyProfile,
} from '@sosed/api-client';
import { defaultCity, useCities } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import {
  Badge,
  Banner,
  Card,
  Heading,
  NumIcon,
  Option,
  RadioGroup,
  RowIcon,
  Text,
} from '@sosed/ui-web';
import { useSearch } from '@tanstack/react-router';
import { useRef, useState } from 'react';

import { SaveError } from '../shared/SaveError.tsx';
import { WizardHeader } from '../shared/WizardHeader.tsx';
import { useBecomeFlow, useDraftProfile, useStepButton } from '../shared/flow.ts';
import type { BecomeSearch } from '../shared/paths.ts';

const KINDS: readonly { kind: ProfileKind; icon: IconName; palette?: AvatarPalette }[] = [
  { kind: 'pro', icon: 'briefcase' },
  { kind: 'casual', icon: 'clock', palette: 3 },
];

const NEEDS = ['needs1', 'needs2', 'needs3'] as const;

export function TypeScreen() {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const flow = useBecomeFlow();
  const search: BecomeSearch = useSearch({ strict: false });
  const me = useIdentityGetMe();
  const cities = useCities(useLocale());
  const { query, draft } = useDraftProfile({ allowMissing: true });
  const [chosen, setChosen] = useState<ProfileKind | null>(null);
  const kind = chosen ?? draft?.kind ?? search.kind ?? 'pro';
  // Idempotency-Key создания — один на тип: повтор после потерянного ответа вернёт тот же черновик
  const key = useRef<string | null>(null);

  const next = (profile: ProfileOut) => {
    flow.saved(profile);
    flow.open('about');
  };
  const create = useSpecialistsCreateMyProfile({
    mutation: {
      onSuccess: next,
      // черновик уже создан (ответ потерялся, тип сменили) — перечитываем: дальше его правит PATCH
      onError: (error) => {
        if (error instanceof ApiError && error.code === 'profile_exists') void query.refetch();
      },
    },
  });
  const update = useSpecialistsUpdateMyProfile({ mutation: { onSuccess: next } });
  const pending = create.isPending || update.isPending;

  const submit = () => {
    if (pending || query.isPending) return;
    if (draft) {
      if (draft.kind === kind) flow.open('about');
      else update.mutate({ data: { kind } });
      return;
    }
    const cityId = me.data?.home_city_id ?? defaultCity(cities.data ?? [], null);
    if (cityId === null) return;
    key.current ??= crypto.randomUUID();
    create.mutate({ data: { kind, city_id: cityId }, headers: { 'Idempotency-Key': key.current } });
  };
  // пока не знаем, есть ли черновик, нажатие ничего не сделало бы — кнопка показывает загрузку
  useStepButton({
    text: common('action.next'),
    onClick: submit,
    loading: pending || query.isPending,
  });
  useBackButton(() => flow.back(null));

  const choose = (next: ProfileKind) => {
    platform.haptics.selection();
    if (next !== kind) key.current = null;
    setChosen(next);
  };

  const error = update.error ?? create.error;
  return (
    <section className="flex flex-col gap-5 px-4 pt-3 pb-6">
      <WizardHeader step={1} title={t('become.type.title')} intro={t('become.type.intro')} />
      <RadioGroup label={t('become.type.label')} busy={pending} className="flex flex-col gap-3">
        {KINDS.map((option) => (
          <Option
            key={option.kind}
            large
            leading={<RowIcon icon={option.icon} palette={option.palette} xl />}
            title={t(`become.type.${option.kind}.title`)}
            description={
              option.kind === 'casual' ? (
                <>
                  {t('become.type.casual.text')}
                  <span className="mt-1 flex items-start gap-1.5">
                    <Badge>{t('become.type.casualMark')}</Badge>
                    <Text as="span" variant="cap" className="min-w-0 pt-0.5">
                      {t('become.type.casualMarkNote')}
                    </Text>
                  </span>
                </>
              ) : (
                t('become.type.pro.text')
              )
            }
            checked={option.kind === kind}
            onChange={() => choose(option.kind)}
          />
        ))}
      </RadioGroup>
      <Banner tone="info">{t('become.type.casualFree')}</Banner>
      <Card as="section" tight>
        <Heading variant="h3" as="h2">
          {t('become.type.needsTitle')}
        </Heading>
        <ol className="m-0 flex list-none flex-col gap-2 p-0">
          {NEEDS.map((need, index) => (
            <li key={need} className="flex items-center gap-2.5">
              <NumIcon>{index + 1}</NumIcon>
              <Text variant="sm">{t(`become.type.${need}`)}</Text>
            </li>
          ))}
        </ol>
      </Card>
      {error && <SaveError error={error} />}
    </section>
  );
}
