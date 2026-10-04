// Корневой экран (DEVELOPMENT_PLAN 8.1): в Telegram — оболочка с таббаром, в браузере — своя.
// Оболочка браузера и правила «что открыто вне Telegram» (routes/browser.ts) — одним своим чанком:
// первый экран в Telegram их не качает.
import { usePlatform } from '@sosed/platform';
import { lazy, Suspense } from 'react';

import { AppShell } from '../features/shell/index.ts';

const BrowserShell = lazy(() =>
  Promise.all([import('../features/shell/web/BrowserShell.tsx'), import('./browser.ts')]).then(
    ([shell, rules]) => ({
      default: () => <shell.BrowserShell blockedStart={rules.browserStart} />,
    }),
  ),
);

export function RootShell() {
  const platform = usePlatform();
  if (platform.kind !== 'browser') return <AppShell />;
  return (
    <Suspense fallback={null}>
      <BrowserShell />
    </Suspense>
  );
}
