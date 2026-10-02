// Места заявки строкой карточки (.slots + «3 из 5»): шапка отклика S16 и карточки «Мои отклики»
// S17. Короче, чем в ленте: «3 из 5» видно, «откликов 3 из 5» — скринридеру.
import { useTranslation } from '@sosed/i18n';
import { cx } from '@sosed/ui-web';

import { useSlots } from './labels.ts';

export function MiniSlots({ job }: { job: { max_responses: number; responses_count: number } }) {
  const { t } = useTranslation('jobs');
  const slots = useSlots()(job);
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <span aria-hidden="true" className="flex gap-0.75">
        {Array.from({ length: slots.total }, (_, index) => (
          <i
            key={index}
            className={cx(
              'h-1.5 w-3.5 rounded-full',
              index < slots.taken ? 'bg-accent' : 'bg-line',
            )}
          />
        ))}
      </span>
      <span className="text-cap text-text2" aria-hidden="true">
        {t('respond.slots', { count: slots.taken, total: slots.total })}
      </span>
      <span className="sr-only">{slots.label}</span>
    </span>
  );
}
