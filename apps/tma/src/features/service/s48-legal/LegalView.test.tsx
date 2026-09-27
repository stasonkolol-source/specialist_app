// S48 (DEVELOPMENT_PLAN 1.5a): тексты черновиков 0.27 из client-config, разделы как пункты
// макета, пометка без перевода, безопасный Markdown и состояния загрузки. API — MSW; axe — в e2e.
import type { ClientConfigOut } from '@sosed/api-client';
import { configureApiClient } from '@sosed/api-client';
import { getSystemGetClientConfigMockHandler } from '@sosed/api-client/mocks';
import type { LegalDocumentKey } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import { PlatformProvider, createMockPlatform } from '@sosed/platform';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import { CLIENT_CONFIG } from '../../../testing/fixtures.ts';
import { API_ORIGIN, server } from '../../../testing/msw.ts';
import { LegalView } from './LegalView.tsx';
import { outline } from './sections.ts';

function renderView(document: LegalDocumentKey = 'terms', locale: Locale = 'ru') {
  const i18n = createI18n({ locale, appName: 'Сосед' });
  configureApiClient({ baseUrl: API_ORIGIN, locale: () => currentLocale(i18n) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDocumentChange = vi.fn();
  const view = render(
    <PlatformProvider platform={createMockPlatform().platform}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <LegalView document={document} onDocumentChange={onDocumentChange} />
        </QueryClientProvider>
      </I18nextProvider>
    </PlatformProvider>,
  );
  return { ...view, onDocumentChange };
}

const withTerms = (body: string): ClientConfigOut => ({
  ...CLIENT_CONFIG,
  legal_documents: {
    terms: { version: '1.0', published_on: '2026-09-26', texts: { ru: { title: 'П', body } } },
  },
});

describe('outline', () => {
  it('splits the document into numbered sections after the intro', () => {
    const { intro, sections } = outline('Вступление.\n\n## 1. Первый\n\nТекст.\n\n## Контакты\n');
    expect(intro).toHaveLength(1);
    expect(sections.map((s) => s.number)).toEqual(['1', null]);
    expect(sections[0]?.title).toEqual([{ type: 'text', value: 'Первый' }]);
    expect(sections[0]?.blocks).toHaveLength(1);
    expect(sections[1]?.title).toEqual([{ type: 'text', value: 'Контакты' }]);
  });
});

describe('S48 legal documents', () => {
  it('shows the current edition of the rules as numbered sections', async () => {
    const { container } = renderView('terms');

    expect(await screen.findByRole('heading', { name: 'Правила площадки', level: 1 })).toBeTruthy();
    expect(await screen.findByText('Редакция draft-1 от 27 сентября 2026')).toBeTruthy();
    const sections = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(sections[0]).toBe('Кто может пользоваться');
    expect(sections.at(-1)).toBe('Контакты');
    expect(screen.getAllByRole('listitem')[0]?.textContent).toMatch(/^1Кто может пользоваться/);
    // заметки владельца и подстановки до пользователя не доходят
    expect(container.textContent).not.toContain('Решение владельца');
    expect(container.textContent).not.toContain('{{');
    expect(container.textContent).toContain('Сосед помогает');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows the privacy policy with its tables', async () => {
    const { container } = renderView('privacy');

    expect(
      await screen.findByRole('heading', { name: 'Политика конфиденциальности', level: 1 }),
    ).toBeTruthy();
    // таблицы в два столбца остаются таблицами, шире — списком записей «Столбец: значение»
    const tables = await screen.findAllByRole('table');
    expect(tables).toHaveLength(2);
    expect(screen.getByText('Hetzner')).toBeTruthy();
    expect(screen.getAllByText('Для чего:').length).toBeGreaterThan(3);
    expect(
      within(tables[0] as HTMLElement)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(['Цель', 'Основание (ст. 12 ZZPL)']);
    // оператор и почта не решены владельцем (K22): заглушка видна, а не пустое место
    expect(container.textContent).toContain('[TODO K22: оператор данных');
  });

  it('switches documents with the segmented control', async () => {
    const { onDocumentChange } = renderView('terms');
    const segment = await screen.findByRole('radiogroup', { name: 'Документ' });

    await act(async () => {
      fireEvent.click(within(segment).getByRole('radio', { name: 'Конфиденциальность' }));
    });

    expect(onDocumentChange).toHaveBeenCalledWith('privacy');
  });

  it('shows Russian text with a note until the Serbian translation exists', async () => {
    const { container } = renderView('terms', 'sr-Latn');

    expect(
      await screen.findByRole('heading', { name: 'Pravila platforme', level: 1 }),
    ).toBeTruthy();
    expect(await screen.findByText('Verzija draft-1 od 27. septembar 2026.')).toBeTruthy();
    expect(
      screen.getByText('Prevod na srpski još nije gotov — prikazujemo tekst na ruskom'),
    ).toBeTruthy();
    const russian = container.querySelectorAll('[lang="ru"]');
    expect(russian.length).toBeGreaterThan(0);
    expect(russian[0]?.textContent).toContain('Сосед помогает');
  });

  it('shows the translation when it exists', async () => {
    const config = withTerms('Tekst.\n');
    const terms = config.legal_documents.terms;
    if (terms) terms.texts['sr-Latn'] = { title: 'Pravila', body: '## 1. Ko može\n\nTekst.\n' };
    server.use(getSystemGetClientConfigMockHandler(config));
    renderView('terms', 'sr-Latn');

    expect(await screen.findByRole('heading', { name: 'Ko može', level: 2 })).toBeTruthy();
    expect(screen.queryByText(/Prevod na srpski/)).toBeNull();
  });

  it('never renders HTML from the text', async () => {
    server.use(
      getSystemGetClientConfigMockHandler(
        withTerms('## 1. Раздел\n\n<img src="x" onerror="alert(1)"> и <script>alert(2)</script>\n'),
      ),
    );
    const { container } = renderView('terms');

    expect(await screen.findByRole('heading', { name: 'Раздел', level: 2 })).toBeTruthy();
    expect(container.querySelector('img, script')).toBeNull();
    expect(container.textContent).toContain('<img src="x" onerror="alert(1)">');
  });

  it('says the document is unavailable when its version has no text', async () => {
    server.use(getSystemGetClientConfigMockHandler({ ...CLIENT_CONFIG, legal_documents: {} }));
    renderView('privacy');

    expect(await screen.findByRole('heading', { name: 'Документ недоступен' })).toBeTruthy();
    expect(screen.queryByText(/^Редакция/)).toBeNull();
  });

  it('shows S49a with retry when client-config cannot be reached', async () => {
    server.use(http.get('*/api/v1/client-config', () => HttpResponse.error(), { once: true }));
    renderView('terms');

    expect(await screen.findByRole('heading', { name: 'Нет соединения' })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });

    expect(await screen.findByText('Редакция draft-1 от 27 сентября 2026')).toBeTruthy();
  });

  it('announces loading until client-config answers', async () => {
    renderView('terms');
    expect(screen.getByRole('status').textContent).toBe('Загружаем документ');
    expect(await screen.findByRole('heading', { name: 'Кто может пользоваться' })).toBeTruthy();
  });
});
