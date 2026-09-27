import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { checkCatalogs } from '../scripts/i18n.ts';
import { createI18n } from './instance.ts';
import { I18nextProvider, useFormat, useTranslation } from './react.ts';

describe('экземпляр i18next', () => {
  it('ICU-плюралы через t()', () => {
    const i18n = createI18n({ locale: 'ru', appName: 'Соседи' });
    expect(i18n.t('count.reviews', { count: 37 })).toBe('37 отзывов');
    expect(i18n.t('status.deal.agreed')).toBe('Договорились');
  });

  it('{appName} из конфига; для sr-Latn — латиницей и после смены языка', async () => {
    const i18n = createI18n({ locale: 'sr-Cyrl', appName: 'Соседи' });
    expect(i18n.t('app.name')).toBe('Соседи');
    await i18n.changeLanguage('sr-Latn');
    expect(i18n.t('app.name')).toBe('Sosedi');
    expect(i18n.t('status.job.published')).toBe('Objavljen');
    await i18n.changeLanguage('ru');
    expect(i18n.t('app.name')).toBe('Соседи');
  });

  it('хуки useTranslation и useFormat', () => {
    const i18n = createI18n({ locale: 'sr-Latn', appName: 'Соседи' });
    function Probe() {
      const { t } = useTranslation();
      const format = useFormat();
      return <p>{`${t('rating.new')} · ${format.money(500_000)}`}</p>;
    }
    const html = renderToString(
      <I18nextProvider i18n={i18n}>
        <Probe />
      </I18nextProvider>,
    );
    expect(html).toContain('Novi stručnjak · 5.000');
  });
});

describe('каталоги (make i18n-check)', () => {
  it('sr-Latn актуален, ключи и аргументы ru и sr-Cyrl совпадают, ICU без ошибок', () => {
    expect(checkCatalogs()).toEqual([]);
  });
});
