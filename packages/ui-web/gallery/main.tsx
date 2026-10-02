// Галерея: ?theme=light|dark&lang=ru|sr-Latn|sr-Cyrl. Эталон для сверки — design/project/Main.dc.html.
import { I18nextProvider, createI18n, i18nReady, isLocale } from '@sosed/i18n';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import './gallery.css';
import { Gallery } from './Gallery.tsx';

const params = new URLSearchParams(window.location.search);
const theme = params.get('theme') === 'dark' ? 'dark' : 'light';
const lang = params.get('lang');
const locale = isLocale(lang) ? lang : 'ru';

document.documentElement.dataset.theme = theme;
document.documentElement.lang = locale;

const i18n = createI18n({ locale, appName: 'Соседи' });
const root = document.getElementById('root');
// сербские тексты — отдельным чанком, как в приложении: первый кадр — уже с ними
void i18nReady(i18n).then(() => {
  if (!root) return;
  createRoot(root).render(
    <StrictMode>
      <I18nextProvider i18n={i18n}>
        <Gallery theme={theme} locale={locale} />
      </I18nextProvider>
    </StrictMode>,
  );
});
