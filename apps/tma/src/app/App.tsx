// Провайдеры-синглтоны точки сборки (ADR-0020 §13): платформа, i18n, QueryClient, роутер.
// Фичи получают их через контекст и не импортируют app/.
import type { createI18n } from '@sosed/i18n';
import { I18nextProvider } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { PlatformProvider, useThemeSync } from '@sosed/platform';
import type { QueryClient } from '@tanstack/react-query';
import { QueryClientProvider } from '@tanstack/react-query';
import type { AnyRouter } from '@tanstack/react-router';
import { RouterProvider } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useLayoutEffect } from 'react';

import { ReportHost } from '../features/safety/index.ts';
import { CHROME } from './chrome.ts';
import { ErrorBoundary } from './ErrorBoundary.tsx';
import { LaunchGate } from './LaunchGate.tsx';
import { reloadRoutes } from './router.ts';
import type { Auth } from './session.ts';
import { StartupGate } from './StartupGate.tsx';

export interface AppProps {
  platform: Platform;
  i18n: ReturnType<typeof createI18n>;
  queryClient: QueryClient;
  router: AnyRouter;
  version: string;
  launch: Auth['launch'];
  deepLink: string | null;
}

/** Скрытый WebView кадров не рисует: ready() — не позже, заглушку Telegram не держим. */
const READY_FALLBACK_MS = 500;

export function App({ platform, i18n, queryClient, router, version, launch, deepLink }: AppProps) {
  useReadyAfterFirstFrame(platform);
  return (
    <PlatformProvider platform={platform}>
      <I18nextProvider i18n={i18n}>
        <ThemeSync>
          {/* QueryClient над экраном ошибки: S49b в нём открывает правила площадки из конфига */}
          <QueryClientProvider client={queryClient}>
            <ErrorBoundary onReset={() => reloadRoutes(router)}>
              <StartupGate appVersion={version}>
                <LaunchGate launch={launch} deepLink={deepLink} router={router}>
                  <RouterProvider router={router} />
                  {/* шторка жалобы S46 — над любым экраном, своим чанком (4.7) */}
                  <ReportHost />
                </LaunchGate>
              </StartupGate>
            </ErrorBoundary>
          </QueryClientProvider>
        </ThemeSync>
      </I18nextProvider>
    </PlatformProvider>
  );
}

/** Telegram показывает свою заглушку, пока не получит ready(): сигнал — с первым кадром приложения
 *  (S01 или S49), а не до рендера. Иначе между заглушкой и S01 мелькал бы пустой экран. */
function useReadyAfterFirstFrame(platform: Platform) {
  useLayoutEffect(() => {
    let sent = false;
    const ready = () => {
      if (sent) return;
      sent = true;
      platform.ready();
    };
    const frame = requestAnimationFrame(ready);
    const fallback = setTimeout(ready, READY_FALLBACK_MS);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(fallback);
    };
  }, [platform]);
}

/** Тема и цвета клиента Telegram — над всем приложением: экраны S49 при старте и экран ошибки
 *  рисуются без оболочки маршрутов, но в теме пользователя. */
function ThemeSync({ children }: { children: ReactNode }) {
  useThemeSync(CHROME);
  return children;
}
