// Шапка шага по артбордам S20a–d: полоски, «Шаг N из 4 · черновик сохраняется сам», заголовок.
import { useTranslation } from '@sosed/i18n';
import { Heading, Steps, Text } from '@sosed/ui-web';

import { CREATE_STEPS } from './paths.ts';

export function WizardHeader({ step, title }: { step: 1 | 2 | 3 | 4; title: string }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const total = CREATE_STEPS.length;
  return (
    <>
      <div className="flex flex-col gap-2">
        <Steps
          total={total}
          current={step}
          label={common('form.step', { current: step, total })}
        />
        <Text variant="cap">{t('create.step', { current: step, total })}</Text>
      </div>
      <Heading variant="h2" as="h1">
        {title}
      </Heading>
    </>
  );
}
