// S02b «Что вы хотите?», шаг 2 из 3 (DEVELOPMENT_PLAN 1.5b): намерение → PATCH /me {intent}.
// Намерение настраивает стартовый экран и подсказки, прав не даёт (ADR-0009). По умолчанию —
// «Найти мастера», как на артборде. «Назад» — на S02a, даже если шаг открыли сразу при запуске.
import type { UserIntent } from '@sosed/api-client';
import { useIdentityGetMe, useIdentityUpdateMe } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import type { AvatarPalette, IconName } from '@sosed/ui-web';
import { useBackButton, usePlatform } from '@sosed/platform';
import { Banner, Option, RadioGroup, RowIcon } from '@sosed/ui-web';

import { SaveError } from '../shared/SaveError.tsx';
import { StepHeader } from '../shared/StepHeader.tsx';
import { useOnboardingFlow, useStepButton } from '../shared/flow.ts';
import { useOnboardingStore } from '../shared/store.ts';

const INTENTS: readonly { intent: UserIntent; icon: IconName; palette: AvatarPalette }[] = [
  { intent: 'client', icon: 'search', palette: 1 },
  { intent: 'pro', icon: 'briefcase', palette: 2 },
  { intent: 'casual', icon: 'wallet', palette: 3 },
];

const DEFAULT_INTENT: UserIntent = 'client';

export function IntentScreen() {
  const { t } = useTranslation('onboarding');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const flow = useOnboardingFlow();
  const me = useIdentityGetMe();
  const draft = useOnboardingStore((state) => state.intent);
  const setDraft = useOnboardingStore((state) => state.set);
  const intent = draft ?? me.data?.intent ?? DEFAULT_INTENT;

  const update = useIdentityUpdateMe({
    mutation: { onSuccess: (next) => flow.saved('intent', next) },
  });
  const submit = () => {
    if (!update.isPending) update.mutate({ data: { intent } });
  };
  useStepButton({ text: common('action.next'), onClick: submit, loading: update.isPending });
  useBackButton(() => flow.back('language'));

  const choose = (next: UserIntent) => {
    platform.haptics.selection();
    setDraft({ intent: next });
  };

  return (
    <section className="flex flex-col gap-5 px-4 pt-4 pb-6">
      <StepHeader step={2} title={t('intent.title')} intro={t('intent.intro')} />
      <RadioGroup label={t('intent.label')} className="flex flex-col gap-3">
        {INTENTS.map((option) => (
          <Option
            key={option.intent}
            large
            leading={<RowIcon icon={option.icon} palette={option.palette} xl />}
            title={t(`intent.${option.intent}.title`)}
            description={t(`intent.${option.intent}.text`)}
            checked={option.intent === intent}
            onChange={() => choose(option.intent)}
          />
        ))}
      </RadioGroup>
      <Banner tone="info">{t('intent.free')}</Banner>
      {update.isError && <SaveError error={update.error} />}
    </section>
  );
}
