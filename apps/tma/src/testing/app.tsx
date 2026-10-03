// Приложение целиком на mock-платформе для тестов сценариев (DEVELOPMENT_PLAN 1.5b): та же точка
// сборки, что в main.tsx, memory history и MSW. MainButton и BackButton Telegram — нативные (в DOM
// их нет): нажатие — событием клиента, состояние — по вызовам web_app_setup_*.
import type { ConsentsIn, MeOut, MeUpdateIn } from '@sosed/api-client';
import { getIdentityAuthenticateTelegramMockHandler } from '@sosed/api-client/mocks';
import type { ColorScheme, MockTelegram } from '@sosed/platform';
import { createMockPlatform } from '@sosed/platform/mock';
import { createMemoryHistory } from '@tanstack/react-router';
import { act, render } from '@testing-library/react';
import { HttpResponse, http } from 'msw';

import { App } from '../app/App.tsx';
import { assemble } from '../app/bootstrap.ts';
import {
  DELETION_EXECUTE_AFTER,
  DELETION_REQUESTED_AT,
  WRITE_ACCESS,
  accepted,
} from './fixtures.ts';
import { API_ORIGIN, TOKENS, server } from './msw.ts';

export interface StartOptions {
  languageCode?: string;
  /** Код `startapp` запуска (deep link). */
  startParam?: string;
  /** Ответ клиента на requestWriteAccess. */
  writeAccess?: boolean;
  colorScheme?: ColorScheme;
  /** Кнопка, которую «нажмёт» человек в нативном попапе; null — закрыл попап. */
  popupAnswer?: string | null;
  /** Что уже лежит в DeviceStorage Telegram. */
  deviceStorage?: Record<string, string>;
}

export function startApp(path = '/', options: StartOptions = {}) {
  const { languageCode = 'ru', startParam, writeAccess, colorScheme, popupAnswer } = options;
  const { platform, telegram } = createMockPlatform({
    languageCode,
    startParam,
    writeAccess,
    colorScheme,
    popupAnswer,
    deviceStorage: options.deviceStorage,
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
    deletion: [] as ('request' | 'cancel')[],
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
    // S45: grace 7 дней от DELETION_REQUESTED_AT; повтор — тот же срок, отмена идемпотентна
    http.post('*/api/v1/me/deletion', () => {
      requests.deletion.push('request');
      const execute = user.deletion_scheduled_at ?? DELETION_EXECUTE_AFTER;
      user = { ...user, deletion_scheduled_at: execute };
      return HttpResponse.json({ requested_at: DELETION_REQUESTED_AT, execute_after: execute });
    }),
    http.delete('*/api/v1/me/deletion', () => {
      requests.deletion.push('cancel');
      user = { ...user, deletion_scheduled_at: null };
      return new HttpResponse(null, { status: 204 });
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
