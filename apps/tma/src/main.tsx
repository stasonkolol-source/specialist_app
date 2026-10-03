import './app/app.css';

import { i18nReady } from '@sosed/i18n';
import type { Platform } from '@sosed/platform';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App.tsx';
import { assemble } from './app/bootstrap.ts';
import { listenIntent } from './app/intent.ts';
import { selectPlatform } from './app/platform.ts';
import { initSentry } from './app/sentry.ts';
import { startLaunch } from './app/startup.ts';
import { afterFirstScreen } from './features/shell/index.ts';

// mock-клиент (`?platform=mock`, разработка и e2e) приходит своим чанком; в Telegram — сразу
const selected = selectPlatform();
if (selected instanceof Promise) void selected.then(start);
else start(selected);

function start(platform: Platform) {
  const params = new URLSearchParams(window.location.search);
  const app = assemble(platform, {
    version: __APP_VERSION__,
    languages: navigator.languages,
    // в Telegram сохранённый язык (ui_locale) приходит со входом; в mock-режиме — параметром для e2e
    savedLocale: platform.kind === 'mock' ? params.get('locale') : null,
  });
  // вход, client-config, справочники и чанк экрана запуска — сразу, параллельно, до React
  startLaunch(app);
  // палец на ссылке — чанк и данные экрана грузятся до нажатия; следующий экран — в простое
  listenIntent(app);
  // SDK Sentry (≈150 KB) — после входа и данных первого экрана: не отнимает у них сеть
  void app
    .launch()
    .finally(() =>
      afterFirstScreen(
        app.queryClient,
        () => void initSentry(import.meta.env.VITE_SENTRY_DSN, __APP_VERSION__),
      ),
    );

  const root = document.getElementById('root');
  // сербские тексты — отдельным чанком: первый кадр — уже с ними, без мелькания русского.
  // Тексты остальных экранов догружает оболочка (AppShell), когда первый экран дочитал данные
  void i18nReady(app.i18n).then(() => {
    if (!root) return;
    createRoot(root).render(
      <StrictMode>
        <App {...app} />
      </StrictMode>,
    );
  });
}
