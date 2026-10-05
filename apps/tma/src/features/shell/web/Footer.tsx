// Подвал страниц браузерной оболочки (8.1): правила, политика и «Как удалить аккаунт». Одна ссылка
// на удаление под кнопками говорила новичку «отсюда уходят», а документы S48 в браузере открыты
// (routes/browser.ts), но ссылок на них не было. Прижат к низу страницы, переносится строками.
import type { LegalDocumentKey } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';

import { WEB_PATHS } from './paths.ts';

/** S48 (маршрут фичи service): документ — параметр пути, как у ссылки на S02c. */
const LEGAL_PATH = '/legal/$document';

export function WebFooter({ deletion = true }: { deletion?: boolean }) {
  const { t } = useTranslation('web');
  const router = useRouter();
  const link = (label: string, href: string, open: () => void) => (
    <a
      href={router.history.createHref(href)}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        event.preventDefault();
        open();
      }}
      className="inline-flex min-h-11 items-center text-cap text-text2 outline-none focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-accent"
    >
      {label}
    </a>
  );
  const legal = (document: LegalDocumentKey) => () =>
    void router.navigate({ to: LEGAL_PATH, params: { document } });

  return (
    <nav
      aria-label={t('footer.label')}
      className="mt-auto flex flex-wrap justify-center gap-x-4 px-4 pt-6 pb-2"
    >
      {link(t('footer.terms'), '/legal/terms', legal('terms'))}
      {link(t('footer.privacy'), '/legal/privacy', legal('privacy'))}
      {/* на самой странице удаления ссылка на неё не нужна */}
      {deletion &&
        link(
          t('footer.deletion'),
          WEB_PATHS.deletion,
          () => void router.navigate({ to: WEB_PATHS.deletion }),
        )}
    </nav>
  );
}
