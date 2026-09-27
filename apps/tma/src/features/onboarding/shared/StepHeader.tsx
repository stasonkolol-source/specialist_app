// Шапка шага онбординга по артбордам S02a–c: полоски «Шаг N из 3», заголовок .h1, пояснение .t2.
import { useTranslation } from '@sosed/i18n';
import { Heading, Steps, Text } from '@sosed/ui-web';

export const ONBOARDING_TOTAL = 3;

export function StepHeader({
  step,
  title,
  intro,
}: {
  step: 1 | 2 | 3;
  title: string;
  intro?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3">
      <Steps
        total={ONBOARDING_TOTAL}
        current={step}
        label={t('form.step', { current: step, total: ONBOARDING_TOTAL })}
      />
      <Heading variant="h1">{title}</Heading>
      {intro && <Text secondary>{intro}</Text>}
    </div>
  );
}
