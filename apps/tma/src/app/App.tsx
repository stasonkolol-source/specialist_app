// Провайдеры-синглтоны точки сборки (ADR-0020 §13): платформа, i18n, QueryClient, роутер.
// Фичи получают их через контекст и не импортируют app/.
import type { createI18n } from '@sosed/i18n';
import { I18nextProvider } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { PlatformProvider } from '@sosed/platform';
import type { QueryClient } from '@tanstack/react-query';
import { QueryClientProvider } from '@tanstack/react-query';
import type { AnyRouter } from '@tanstack/react-router';
import { RouterProvider } from '@tanstack/react-router';

import { ErrorBoundary } from './ErrorBoundary.tsx';
import { StartupGate } from './StartupGate.tsx';

export interface AppProps {
  platform: Platform;
  i18n: ReturnType<typeof createI18n>;
  queryClient: QueryClient;
  router: AnyRouter;
  version: string;
}

export function App({ platform, i18n, queryClient, router, version }: AppProps) {
  return (
    <PlatformProvider platform={platform}>
      <I18nextProvider i18n={i18n}>
        <ErrorBoundary>
          <QueryClientProvider client={queryClient}>
            <StartupGate appVersion={version}>
              <RouterProvider router={router} />
            </StartupGate>
          </QueryClientProvider>
        </ErrorBoundary>
      </I18nextProvider>
    </PlatformProvider>
  );
}
