import './app/app.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App.tsx';
import { assemble } from './app/bootstrap.ts';
import { selectPlatform } from './app/platform.ts';
import { initSentry } from './app/sentry.ts';

const app = assemble(selectPlatform(), {
  version: __APP_VERSION__,
  languages: navigator.languages,
});
void app.signIn();
void initSentry(import.meta.env.VITE_SENTRY_DSN, __APP_VERSION__);

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App {...app} />
    </StrictMode>,
  );
}
