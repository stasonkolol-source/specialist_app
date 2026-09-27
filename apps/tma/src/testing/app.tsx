// Приложение целиком на mock-платформе для тестов сценариев (DEVELOPMENT_PLAN 1.5b): та же точка
// сборки, что в main.tsx, memory history и MSW. MainButton и BackButton Telegram — нативные (в DOM
// их нет): нажатие — событием клиента, состояние — по вызовам web_app_setup_*.
import type { ConsentsIn, MeOut, MeUpdateIn } from '@sosed/api-client';
import { getIdentityAuthenticateTelegramMockHandler } from '@sosed/api-client/mocks';
import type { ColorScheme, MockTelegram } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform';
import { createMemoryHistory } from '@tanstack/react-router';
import { act, render } from '@testing-library/react';
import { HttpResponse, http } from 'msw';

import { App } from '../app/App.tsx';
import { assemble } from '../app/bootstrap.ts';
import { WRITE_ACCESS, accepted } from './fixtures.ts';
import { API_ORIGIN, TOKENS, server } from './msw.ts';

export interface StartOptions {
  languageCode?: string;
  /** Код `startapp` запуска (deep link). */
  startParam?: string;
  /** Ответ клиента на requestWriteAccess. */
  writeAccess?: boolean;
  colorScheme?: ColorScheme;
}

export function startApp(path = '/', options: StartOptions = {}) {
  const { languageCode = 'ru', startParam, writeAccess, colorScheme } = options;
  const { platform, telegram } = createMockPlatform({
    languageCode,
    startParam,
    writeAccess,
    colorScheme,
  });
  const app = assemble(platform, {
    version: '0.1.0',
    history: createMemoryHistory({ initialEntries: [path] }),
    baseUrl: API_ORIGIN,
  });
  render(<App {...app} />);
  return { app, telegram };
}

/** Последнее состояние MainButton, как его получил клиент Telegram. */
export const mainButton = (telegram: MockTelegram) =>
  telegram.callsOf('web_app_setup_main_button').at(-1);

export const backButtonVisible = (telegram: MockTelegram) =>
  telegram.callsOf('web_app_setup_back_button').at(-1)?.is_visible === true;

export const pressMainButton = (telegram: MockTelegram) =>
  act(async () => {
    telegram.emit('main_button_pressed');
  });

export const pressBackButton = (telegram: MockTelegram) =>
  act(async () => {
    telegram.emit('back_button_pressed');
  });

/**
 * Backend пользователя с памятью: вход отдаёт текущее состояние, PATCH /me и POST /me/consents
 * меняют его, как сервер. `requests` — что приложение прислало.
 */
export function userBackend(initial: MeOut) {
  let user = initial;
  const requests = {
    patch: [] as MeUpdateIn[],
    consents: [] as ConsentsIn[],
    writeAccess: 0,
  };
  server.use(
    getIdentityAuthenticateTelegramMockHandler(() => ({ ...TOKENS, is_new: true, user })),
    http.get('*/api/v1/me', () => HttpResponse.json(user)),
    http.patch('*/api/v1/me', async ({ request }) => {
      const body = (await request.json()) as MeUpdateIn;
      requests.patch.push(body);
      const fields = Object.fromEntries(Object.entries(body).filter(([, v]) => v != null));
      user = { ...user, ...fields } as MeOut;
      return HttpResponse.json(user);
    }),
    http.post('*/api/v1/me/consents', async ({ request }) => {
      requests.consents.push((await request.json()) as ConsentsIn);
      user = accepted(user);
      return HttpResponse.json(user);
    }),
    http.post('*/api/v1/me/telegram/write-access', () => {
      requests.writeAccess += 1;
      return HttpResponse.json(WRITE_ACCESS);
    }),
  );
  return {
    requests,
    get user() {
      return user;
    },
    set user(next: MeOut) {
      user = next;
    },
  };
}
