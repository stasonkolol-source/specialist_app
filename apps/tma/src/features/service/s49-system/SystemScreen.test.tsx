// S49 (DEVELOPMENT_PLAN 1.5a, 2.5b): S49b по виду санкции, сроку и причине, «Обжаловать» —
// MainButton → POST /appeals, правила внутри S49b, экраны поверх приложения (нет сети, техработы,
// обновление, ошибка).
import { configureApiClient } from '@sosed/api-client';
import type { SystemState } from '@sosed/hooks';
import type { Locale } from '@sosed/i18n';
import { I18nextProvider, createI18n, currentLocale } from '@sosed/i18n';
import { PlatformProvider } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform/mock';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { API_ORIGIN, server } from '../../../testing/msw.ts';
import type { RestrictedState } from './store.ts';
import { SystemScreen } from './SystemScreen.tsx';

// 3 октября 18:00 по Белграду (UTC+2)
const UNTIL = new Date('2026-10-03T16:00:00Z');

function renderWith(node: ReactNode, locale: Locale = 'ru') {
  const { platform, telegram } = createMockPlatform();
  const i18n = createI18n({ locale, appName: 'Соседи' });
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

const restricted = (
  restriction: RestrictedState['restriction'],
  until: Date | null,
  reason: string | null = null,
) =>
  ({
    kind: 'restricted',
    restriction,
    until,
    blocking: restriction === 'suspended' || restriction === 'banned',
    reason,
  }) satisfies RestrictedState;

const APPEAL = {
  id: '0192a000-0000-7000-8000-000000000001',
  appeal_of: '0192a000-0000-7000-8000-000000000002',
  status: 'pending',
  // 6 октября 18:00 по Белграду
  due_at: '2026-10-06T16:00:00Z',
  created_at: '2026-10-03T16:00:00Z',
  repeated: false,
};

/** POST /appeals: ответ сервера и что пришло в теле. */
function appeals(status: number, body: object) {
  const sent: unknown[] = [];
  server.use(
    http.post(`${API_ORIGIN}/api/v1/appeals`, async ({ request }) => {
      sent.push(await request.json());
      return HttpResponse.json(body, { status });
    }),
  );
  return sent;
}

describe('S49b account restricted', () => {
  it('shows a partial restriction with its term and what stays available', async () => {
    const { telegram } = renderWith(
      <SystemScreen state={restricted('responding_blocked', UNTIL)} onRetry={vi.fn()} />,
    );

    // S49b — своим чанком: приходит только ответом сервера
    expect(
      await screen.findByRole('heading', { name: 'Аккаунт ограничен до 3 октября', level: 1 }),
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
    // причины в старом ответе нет — блока «Решение модератора» тоже
    expect(screen.queryByRole('region', { name: 'Решение модератора' })).toBeNull();
    expect(mainButtonShown(telegram)).toBe(true);
    expect(telegram.callsOf('web_app_setup_main_button').at(-1)).toMatchObject({
      text: 'Обжаловать',
    });
  });

  it('shows the reason and files an appeal with the MainButton', async () => {
    const sent = appeals(201, APPEAL);
    const { telegram } = renderWith(
      <SystemScreen
        state={restricted('responding_blocked', UNTIL, 'prepayment_scam')}
        onRetry={vi.fn()}
      />,
    );
    const decision = await screen.findByRole('region', { name: 'Решение модератора' });
    expect(decision.textContent).toBe('ПричинаПросьбы о предоплате — частая уловка мошенников');

    await act(async () => {
      telegram.emit('main_button_pressed');
    });

    expect((await screen.findByRole('status')).textContent).toBe(
      'Апелляция отправлена. Модератор ответит до 6 октября, 18:00 — ответ придёт в бот.',
    );
    expect(sent).toEqual([{ restriction: 'responding_blocked' }]);
    expect(telegram.callsOf('web_app_setup_main_button').at(-1)).toMatchObject({
      is_visible: false,
    });
  });

  it('says the decision was already appealed and how it ended', async () => {
    appeals(200, { ...APPEAL, repeated: true, status: 'rejected' });
    const { telegram } = renderWith(
      <SystemScreen state={restricted('posting_blocked', null)} onRetry={vi.fn()} />,
    );
    await screen.findByRole('alert');

    await act(async () => {
      telegram.emit('main_button_pressed');
    });

    expect((await screen.findByRole('status')).textContent).toBe(
      'Решение уже обжаловано: модератор оставил его в силе.',
    );
  });

  it('shows the server reason when there is nothing to appeal', async () => {
    appeals(404, {
      type: 'about:blank',
      title: 'Not Found',
      status: 404,
      code: 'appeal_target_not_found',
      detail: 'Обжаловать нечего: решения модерации о вас не нашлось.',
      trace_id: null,
    });
    const { telegram } = renderWith(
      <SystemScreen state={restricted('posting_blocked', null)} onRetry={vi.fn()} />,
    );
    await screen.findByRole('alert');

    await act(async () => {
      telegram.emit('main_button_pressed');
    });

    expect(
      await screen.findByText('Обжаловать нечего: решения модерации о вас не нашлось.'),
    ).toBeTruthy();
    expect(mainButtonShown(telegram)).toBe(true); // можно попробовать снова
  });

  it('closes the whole account without the «still available» list', async () => {
    const { telegram } = renderWith(
      <SystemScreen state={restricted('suspended', UNTIL)} onRetry={vi.fn()} />,
    );
    expect(
      await screen.findByRole('heading', { name: 'Аккаунт приостановлен до 3 октября' }),
    ).toBeTruthy();
    // вход закрыт — сессии для POST /appeals нет: «Обжаловать» не показываем
    expect(mainButtonShown(telegram)).toBe(false);
    expect(screen.getByRole('alert').textContent).toBe(
      'До 3 октября, 18:00 нельзя пользоваться аккаунтом',
    );
    expect(screen.queryByRole('region', { name: 'Остаётся доступно' })).toBeNull();
  });

  it('says a ban is permanent and speaks Serbian', async () => {
    renderWith(<SystemScreen state={restricted('banned', null)} onRetry={vi.fn()} />, 'sr-Latn');
    // сербские тексты — отдельным чанком: экран дорисовывается, когда он загрузился
    expect(await screen.findByRole('heading', { name: 'Nalog je blokiran' })).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('Ne možete da koristite nalog');
  });

  it('opens the platform rules in place and returns with Telegram «Back»', async () => {
    const { telegram } = renderWith(
      <SystemScreen state={restricted('messaging_blocked', null)} onRetry={vi.fn()} />,
    );
    expect((await screen.findByRole('alert')).textContent).toBe('Нельзя начинать новые диалоги');

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
