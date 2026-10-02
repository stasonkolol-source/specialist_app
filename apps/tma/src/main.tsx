import './app/app.css';

import { i18nReady, preloadCatalogs } from '@sosed/i18n';
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
// чанк экрана, с которого открыли (обычно Главная), — тоже сразу, а не после входа: холодный
// старт на «среднем Android» < 2,5 с (DEVELOPMENT_PLAN 4.8)
void app.router.preloadRoute({ to: app.router.state.location.pathname }).catch(() => undefined);
void initSentry(import.meta.env.VITE_SENTRY_DSN, __APP_VERSION__);

const root = document.getElementById('root');
// сербские тексты — отдельным чанком: первый кадр — уже с ними, без мелькания русского
void i18nReady(app.i18n).then(() => {
  if (!root) return;
  createRoot(root).render(
    <StrictMode>
      <App {...app} />
    </StrictMode>,
  );
  // тексты остальных экранов — после первого кадра, когда браузер свободен
  const preload = () => void preloadCatalogs(app.i18n);
  // в Safari (Telegram на iOS) requestIdleCallback нет
  if ('requestIdleCallback' in window) window.requestIdleCallback(preload);
  else setTimeout(preload, 1);
});
