// Шапка шага по артбордам S32a–c: полоски, «Шаг N из 3 · черновик сохраняется сам», заголовок.
import { useTranslation } from '@sosed/i18n';
import { Heading, Steps, Text } from '@sosed/ui-web';

export const BECOME_TOTAL = 3;

export function WizardHeader({
  step,
  title,
  intro,
}: {
  step: 1 | 2 | 3;
  title: string;
  intro?: string;
}) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  return (
    <>
      <div className="flex flex-col gap-2">
        <Steps
          total={BECOME_TOTAL}
          current={step}
          label={common('form.step', { current: step, total: BECOME_TOTAL })}
        />
        <Text variant="cap">{t('become.step', { current: step, total: BECOME_TOTAL })}</Text>
      </div>
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {title}
        </Heading>
        {intro && <Text secondary>{intro}</Text>}
      </div>
    </>
  );
}
