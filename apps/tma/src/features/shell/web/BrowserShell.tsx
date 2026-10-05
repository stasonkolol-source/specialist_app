// Оболочка вне Telegram (DEVELOPMENT_PLAN 8.1): тот же SPA с platform=browser. Своя шапка с
// кнопкой «Назад» (у браузера нет кнопок клиента Telegram) и MainButton в контенте. В браузере
// открыты только гостевой просмотр карточки специалиста S08–S11 и заявки S15, веб-ссылки `/s/…`,
// `/j/…` и «Как удалить аккаунт»; остальное (каталог, вход, создание) — v1: вместо экрана —
// «Открыть в Telegram» с кодом startapp этого экрана (что открыто — решают маршруты,
// routes/browser.ts). Чанк — свой: в Telegram он не грузится. Шапка — знак «Соседей» по центру,
// как название по центру шапки Telegram на артбордах: на всех страницах на одном месте, «Назад» —
// слева. Фон шапки — во всю ширину окна, содержимое — колонкой 512 px.
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useBackButtonState, useBottomButtonState } from '@sosed/platform';
import { Icon } from '@sosed/ui-web';
import type { AnyRouteMatch } from '@tanstack/react-router';
import { Outlet, useRouter, useRouterState } from '@tanstack/react-router';
import { Suspense } from 'react';

import { BUTTON_AREA, ContentMainButton } from '../ContentButton.tsx';
import { BrandMark } from './Brand.tsx';
import { OpenInTelegram } from './OpenInTelegram.tsx';

export interface BrowserShellProps {
  /** Код startapp экрана, которого в браузере нет; `null` — экран открыт и в браузере. */
  blockedStart: (match: AnyRouteMatch | undefined) => string | null;
}

export function BrowserShell({ blockedStart }: BrowserShellProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const blocked = useRouterState({ select: (state) => blockedStart(state.matches.at(-1)) });
  // главная `/` — лендинг; другой закрытый экран — тот же лендинг со строкой «только в Telegram»
  const home = useRouterState({ select: (state) => state.matches.at(-1)?.routeId === '/' });
  const back = useBackButtonState();
  const main = useBottomButtonState('main');
  // вместо экрана — «Открыть в Telegram»: «Назад» — туда, откуда пришли (экран свой не рисуется)
  useBackButton(
    blocked !== null && router.history.canGoBack() ? () => router.history.back() : null,
  );
  const button = blocked === null && main.visible;

  return (
    <div className="flex min-h-dvh flex-col bg-bg2">
      <header className="sticky top-0 z-30 border-b border-line bg-bg">
        {/* сетка 1fr · auto · 1fr — стилем элемента: свой класс лёг бы в общий CSS первого экрана */}
        <div
          className="mx-auto grid h-13 max-w-lg items-center px-2"
          style={{ gridTemplateColumns: '1fr auto 1fr' }}
        >
          <div className="flex">
            {back.visible && (
              <button
                type="button"
                onClick={back.click}
                className="inline-flex min-h-11 items-center gap-1 rounded-btn border-0 bg-transparent pr-3 pl-1 text-body font-semibold text-accent outline-none focus-visible:outline-2 focus-visible:outline-accent"
              >
                <Icon name="chev-left" />
                {t('action.back')}
              </button>
            )}
          </div>
          <BrandMark />
        </div>
      </header>
      <main
        className="mx-auto flex w-full max-w-lg flex-1 flex-col"
        style={{ paddingBottom: button ? BUTTON_AREA : 0 }}
      >
        {/* тексты страниц оболочки — своим чанком (неймспейс web) */}
        <Suspense fallback={null}>
          {blocked === null ? <Outlet /> : <OpenInTelegram start={blocked} closed={!home} />}
        </Suspense>
      </main>
      {button && <ContentMainButton />}
    </div>
  );
}
