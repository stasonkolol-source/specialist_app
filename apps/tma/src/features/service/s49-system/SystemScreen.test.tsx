// S49 (DEVELOPMENT_PLAN 1.5a): S49b по виду санкции и сроку, правила внутри S49b, экраны поверх
// приложения (нет сети, техработы, обновление, ошибка). Кнопки «Обжаловать» до 2.5b нет.
import { configureApiClient } from '@sosed/api-client';
import type { SystemState } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import { PlatformProvider, createMockPlatform } from '@sosed/platform';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { API_ORIGIN } from '../../../testing/msw.ts';
import type { RestrictedState } from './store.ts';
import { SystemScreen } from './SystemScreen.tsx';

// 3 октября 18:00 по Белграду (UTC+2)
const UNTIL = new Date('2026-10-03T16:00:00Z');

function renderWith(node: ReactNode, locale: Locale = 'ru') {
  const { platform, telegram } = createMockPlatform();
  const i18n = createI18n({ locale, appName: 'Сосед' });
  configureApiClient({ baseUrl: API_ORIGIN, locale: () => currentLocale(i18n) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <PlatformProvider platform={platform}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>
      </I18nextProvider>
    </PlatformProvider>,
  );
  return { ...view, telegram };
}

/** «Обжаловать» на артборде — MainButton Telegram: в DOM её нет, смотрим вызовы клиента. */
const mainButtonShown = (telegram: ReturnType<typeof renderWith>['telegram']) =>
  telegram.callsOf('web_app_setup_main_button').some((params) => params?.is_visible === true);

const restricted = (restriction: RestrictedState['restriction'], until: Date | null) =>
  ({
    kind: 'restricted',
    restriction,
    until,
    blocking: restriction === 'suspended' || restriction === 'banned',
  }) satisfies RestrictedState;

describe('S49b account restricted', () => {
  it('shows a partial restriction with its term and what stays available', () => {
    const { telegram } = renderWith(
      <SystemScreen state={restricted('responding_blocked', UNTIL)} onRetry={vi.fn()} />,
    );

    expect(
      screen.getByRole('heading', { name: 'Аккаунт ограничен до 3 октября', level: 1 }),
    ).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe(
      'До 3 октября, 18:00 нельзя откликаться на заявки',
    );
    const left = screen.getByRole('region', { name: 'Остаётся доступно' });
    expect(
      within(left)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual([
      'Переписка по текущим сделкам',
      'Просмотр заявок и специалистов',
      'Настройки и удаление аккаунта',
    ]);
    expect(
      screen.getByText('Обжаловать решение можно в течение 6 месяцев. Ответим в течение 72 часов.'),
    ).toBeTruthy();
    // «Обжаловать» включает шаг 2.5b
    expect(screen.queryByRole('button', { name: 'Обжаловать' })).toBeNull();
    expect(mainButtonShown(telegram)).toBe(false);
  });

  it('closes the whole account without the «still available» list', () => {
    renderWith(<SystemScreen state={restricted('suspended', UNTIL)} onRetry={vi.fn()} />);
    expect(
      screen.getByRole('heading', { name: 'Аккаунт приостановлен до 3 октября' }),
    ).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe(
      'До 3 октября, 18:00 нельзя пользоваться аккаунтом',
    );
    expect(screen.queryByRole('region', { name: 'Остаётся доступно' })).toBeNull();
  });

  it('says a ban is permanent and speaks Serbian', () => {
    renderWith(<SystemScreen state={restricted('banned', null)} onRetry={vi.fn()} />, 'sr-Latn');
    expect(screen.getByRole('heading', { name: 'Nalog je blokiran' })).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('Ne možete da koristite nalog');
  });

  it('opens the platform rules in place and returns with Telegram «Back»', async () => {
    const { telegram } = renderWith(
      <SystemScreen state={restricted('messaging_blocked', null)} onRetry={vi.fn()} />,
    );
    expect(screen.getByRole('alert').textContent).toBe('Нельзя начинать новые диалоги');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Правила площадки' }));
    });

    expect(screen.getByRole('heading', { name: 'Правила площадки', level: 1 })).toBeTruthy();
    expect(await screen.findByText('Редакция draft-1 от 27 сентября 2026')).toBeTruthy();
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)).toMatchObject({
      is_visible: true,
    });

    await act(async () => {
      telegram.emit('back_button_pressed');
    });

    expect(screen.getByRole('heading', { name: 'Аккаунт ограничен', level: 1 })).toBeTruthy();
    expect(telegram.callsOf('web_app_setup_back_button').at(-1)).toMatchObject({
      is_visible: false,
    });
    expect(screen.queryByRole('button', { name: 'Обжаловать' })).toBeNull();
    expect(mainButtonShown(telegram)).toBe(false);
  });
});

describe('S49 over the whole app', () => {
  it.each<[SystemState, string, string | null]>([
    [{ kind: 'offline' }, 'Нет соединения', 'Повторить'],
    [{ kind: 'maintenance' }, 'Технические работы', 'Повторить'],
    [{ kind: 'error', traceId: null }, 'Что-то пошло не так', 'Повторить'],
    [{ kind: 'update', target: 'telegram' }, 'Обновите Telegram', null],
    [{ kind: 'update', target: 'app' }, 'Вышла новая версия', 'Перезагрузить'],
  ])('%o → «%s»', async (state, title, action) => {
    const onRetry = vi.fn();
    renderWith(<SystemScreen state={state} onRetry={onRetry} />);

    expect(screen.getByRole('heading', { name: title, level: 1 })).toBeTruthy();
    const buttons = screen.queryAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual(action ? [action] : []);
    if (action === 'Повторить') {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: action }));
      });
      expect(onRetry).toHaveBeenCalledOnce();
    }
  });
});
