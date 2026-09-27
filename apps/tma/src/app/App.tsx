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

export function App({ platform, i18n, queryClient, router, version, launch, deepLink }: AppProps) {
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
                </LaunchGate>
              </StartupGate>
            </ErrorBoundary>
          </QueryClientProvider>
        </ThemeSync>
      </I18nextProvider>
    </PlatformProvider>
  );
}

/** Тема и цвета клиента Telegram — над всем приложением: экраны S49 при старте и экран ошибки
 *  рисуются без оболочки маршрутов, но в теме пользователя. */
function ThemeSync({ children }: { children: ReactNode }) {
  useThemeSync(CHROME);
  return children;
}
