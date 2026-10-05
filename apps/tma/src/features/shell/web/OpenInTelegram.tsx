// Корневая страница вне Telegram (8.1): главная `/`, битые веб-ссылки и экраны, которых в браузере
// нет. Короткий лендинг из утверждённых элементов: знак S01, слоган с городом, одна кнопка «Открыть
// в Telegram» — ссылка на бота с кодом startapp того же экрана (Telegram откроет Mini App сразу на
// нём), три правила S02c о защите от обмана и подвал с документами. Закрытому экрану — строка о
// том, почему он здесь не открылся.
import { useTranslation } from '@sosed/i18n';
import type { IconName } from '@sosed/ui-web';
import { Banner, Button, RowIcon, Text } from '@sosed/ui-web';

import { BrandHero } from './Brand.tsx';
import { WebFooter } from './Footer.tsx';
import { telegramLink } from './links.ts';

/** Правила S02c на лендинге: иконка и первая фраза правила (неймспейс onboarding). */
const TRUST: readonly { icon: IconName; rule: 'reviews' | 'contacts' | 'payment' }[] = [
  { icon: 'shield', rule: 'reviews' },
  { icon: 'chat', rule: 'contacts' },
  { icon: 'wallet', rule: 'payment' },
];

export interface OpenInTelegramProps {
  /** Код startapp экрана. */
  start: string;
  /** Экран есть только в Telegram (не главная и не битая ссылка): строка-объяснение. */
  closed?: boolean;
}

export function OpenInTelegram({ start, closed = false }: OpenInTelegramProps) {
  const { t } = useTranslation('web');
  const { t: rules } = useTranslation('onboarding');
  const href = telegramLink(start);

  return (
    <div className="flex flex-1 flex-col px-4 pt-3 pb-4">
      {closed && (
        <Banner tone="info" icon="info">
          {t('landing.closed')}
        </Banner>
      )}
      <section className="flex flex-col items-center gap-3 pt-10 pb-8 text-center">
        <BrandHero />
        <Text secondary className="max-w-80 text-balance">
          {t('landing.tagline')}
        </Text>
        <div className="mt-3 w-full">
          {href ? (
            <Button href={href} full icon="send">
              {t('link.open')}
            </Button>
          ) : (
            <Banner tone="info">{t('link.noBot')}</Banner>
          )}
        </div>
      </section>
      <ul
        aria-label={rules('rules.title')}
        className="m-0 flex list-none flex-col gap-3.5 rounded-card bg-surface p-4"
      >
        {TRUST.map(({ icon, rule }) => (
          <li key={rule} className="flex items-center gap-3 text-sm">
            <RowIcon icon={icon} />
            {rules(`rules.${rule}.lead`)}
          </li>
        ))}
      </ul>
      <WebFooter />
    </div>
  );
}
