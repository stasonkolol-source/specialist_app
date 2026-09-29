import './app/app.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App.tsx';
import { assemble } from './app/bootstrap.ts';
import { selectPlatform } from './app/platform.ts';
import { initSentry } from './app/sentry.ts';

const platform = selectPlatform();
const params = new URLSearchParams(window.location.search);
const app = assemble(platform, {
  version: __APP_VERSION__,
  languages: navigator.languages,
  // в Telegram сохранённый язык (ui_locale) приходит со входом; в mock-режиме — параметром для e2e
  savedLocale: platform.kind === 'mock' ? params.get('locale') : null,
});
// вход — сразу, параллельно с client-config: экран запуска S01 (LaunchGate) дождётся того же итога
void app.launch();
void initSentry(import.meta.env.VITE_SENTRY_DSN, __APP_VERSION__);

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App {...app} />
    </StrictMode>,
  );
}
