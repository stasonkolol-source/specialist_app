// Страница «Открыть в Telegram / Продолжить в браузере» (8.1). Ссылка на бота — с кодом startapp
// того же экрана: Telegram откроет Mini App сразу на нём. «Продолжить в браузере» — только у
// карточки специалиста и заявки (гостевой просмотр); остальное в браузере — v1, там одна ссылка.
import { useTranslation } from '@sosed/i18n';
import { Banner, Button, EmptyState, LinkButton, Text } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';

import { telegramLink } from './links.ts';
import { WEB_PATHS } from './paths.ts';

export interface OpenInTelegramProps {
  /** Код startapp экрана. */
  start: string;
  /** Заголовок: что открыли (профиль, заявка); по умолчанию — о приложении. */
  title?: string;
  /** Гостевой просмотр в браузере; без него — только ссылка на Telegram. */
  onContinue?: () => void;
}

export function OpenInTelegram({ start, title, onContinue }: OpenInTelegramProps) {
  const { t } = useTranslation('web');
  const router = useRouter();
  const href = telegramLink(start);
  const openDeletion = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: WEB_PATHS.deletion });
  };

  return (
    <section className="flex flex-1 flex-col justify-center gap-4 px-4 pt-3 pb-6">
      <EmptyState
        icon="send"
        title={title ?? t('link.app')}
        as="h1"
        size="h2"
        className="px-2 py-4"
      >
        {t('link.text')}
      </EmptyState>
      <div className="flex flex-col gap-3">
        {href ? (
          <Button href={href} full icon="send">
            {t('link.open')}
          </Button>
        ) : (
          <Banner tone="info">{t('link.noBot')}</Banner>
        )}
        {onContinue && (
          <>
            <Button variant="outline" full onClick={onContinue}>
              {t('link.continue')}
            </Button>
            <Text variant="cap" secondary className="text-center">
              {t('link.browserOnly')}
            </Text>
          </>
        )}
      </div>
      <LinkButton
        href={router.history.createHref(WEB_PATHS.deletion)}
        onClick={openDeletion}
        className="self-center"
      >
        {t('link.deletion')}
      </LinkButton>
    </section>
  );
}
