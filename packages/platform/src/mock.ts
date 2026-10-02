// Mock-клиент Telegram поверх mockTelegramEnv: тот же адаптер tma, а ответы клиента — отсюда.
// Для unit-тестов и разработки вне Telegram.
import { emitEvent, mockTelegramEnv } from '@tma.js/sdk-react';

import { createTmaPlatform } from './tma.ts';
import type { ColorScheme, Platform } from './types.ts';

type Payload = Record<string, unknown>;
const emit = emitEvent as unknown as (event: string, payload?: unknown) => void;

export interface MockOptions {
  version?: string;
  platform?: string;
  colorScheme?: ColorScheme;
  startParam?: string;
  languageCode?: string;
  /** Ответ на `web_app_open_popup`: id кнопки или `null` (закрыт). */
  popupAnswer?: string | null;
  writeAccess?: boolean;
  contact?: boolean;
  location?: { latitude: number; longitude: number } | null;
  /** Настоящий initData вместо синтетического: вход на dev-стенде из браузера
   *  (`cli dev-initdata`). По умолчанию — подпись `mock`, её backend не примет. */
  initData?: string;
  /** Что уже лежит в DeviceStorage: Mini App открыли снова (черновик заявки S20). */
  deviceStorage?: Record<string, string>;
}

export interface MockTelegram {
  /** Вызовы методов Mini App, как их получил бы клиент. */
  calls: { name: string; params: Payload | undefined }[];
  callsOf(name: string): (Payload | undefined)[];
  /** Событие клиента: `main_button_pressed`, `theme_changed`… */
  emit(event: string, payload?: unknown): void;
  setColorScheme(scheme: ColorScheme): void;
}

export const MOCK_THEMES: Record<ColorScheme, Payload> = {
  light: {
    bg_color: '#ffffff',
    text_color: '#111418',
    button_color: '#0b7a5f',
    button_text_color: '#ffffff',
  },
  dark: {
    bg_color: '#17212b',
    text_color: '#f2f5f8',
    button_color: '#3dd6a3',
    button_text_color: '#06281d',
  },
};

export const MOCK_USER = {
  id: 100_000_001,
  first_name: 'Елена',
  last_name: 'К.',
  language_code: 'ru',
};

function initData(languageCode: string, startParam?: string): string {
  const params = new URLSearchParams({
    user: JSON.stringify({ ...MOCK_USER, language_code: languageCode }),
    auth_date: '1790000000',
    signature: 'mock',
    hash: 'mock',
    ...(startParam ? { start_param: startParam } : {}),
  });
  return params.toString();
}

export function createMockPlatform(options: MockOptions = {}): {
  platform: Platform;
  telegram: MockTelegram;
} {
  const {
    version = '9.1',
    platform: clientPlatform = 'tdesktop',
    colorScheme = 'light',
    startParam,
    languageCode = 'ru',
    popupAnswer = 'ok',
    writeAccess = true,
    contact = true,
    location = { latitude: 45.2671, longitude: 19.8335 },
    initData: rawInitData,
    deviceStorage = {},
  } = options;

  const calls: MockTelegram['calls'] = [];
  const device = new Map<string, string>(Object.entries(deviceStorage));
  const cloud = new Map<string, string>();
  let theme = MOCK_THEMES[colorScheme];
  // Ответ клиента асинхронный, как в Telegram
  const reply = (event: string, payload?: unknown) => setTimeout(() => emit(event, payload), 0);

  const handle = (name: string, p: Payload = {}) => {
    const id = p.req_id;
    switch (name) {
      case 'web_app_request_theme':
        return reply('theme_changed', { theme_params: theme });
      case 'web_app_request_viewport':
        return reply('viewport_changed', {
          height: 780,
          width: 390,
          is_expanded: true,
          is_state_stable: true,
        });
      case 'web_app_request_safe_area':
        return reply('safe_area_changed', { top: 47, bottom: 34, left: 0, right: 0 });
      case 'web_app_request_content_safe_area':
        return reply('content_safe_area_changed', { top: 46, bottom: 0, left: 0, right: 0 });
      case 'web_app_open_popup':
        return reply('popup_closed', popupAnswer === null ? {} : { button_id: popupAnswer });
      case 'web_app_request_write_access':
        return reply('write_access_requested', { status: writeAccess ? 'allowed' : 'cancelled' });
      case 'web_app_request_phone':
        return reply('phone_requested', { status: contact ? 'sent' : 'cancelled' });
      case 'web_app_send_prepared_message':
        return reply('prepared_message_sent');
      case 'web_app_check_location':
        return reply('location_checked', {
          available: location !== null,
          access_requested: true,
          access_granted: true,
        });
      case 'web_app_request_location':
        return reply(
          'location_requested',
          location ? { available: true, ...location } : { available: false },
        );
      case 'web_app_device_storage_save_key': {
        if (p.value === null) device.delete(String(p.key));
        else device.set(String(p.key), String(p.value));
        return reply('device_storage_key_saved', { req_id: id });
      }
      case 'web_app_device_storage_get_key':
        return reply('device_storage_key_received', {
          req_id: id,
          value: device.get(String(p.key)) ?? null,
        });
      case 'web_app_invoke_custom_method': {
        const params = (p.params ?? {}) as Payload;
        const keys = (params.keys ?? []) as string[];
        if (p.method === 'saveStorageValue') cloud.set(String(params.key), String(params.value));
        if (p.method === 'deleteStorageValues') for (const key of keys) cloud.delete(key);
        const result =
          p.method === 'getStorageValues'
            ? Object.fromEntries(keys.map((k) => [k, cloud.get(k) ?? '']))
            : true;
        return reply('custom_method_invoked', { req_id: id, result });
      }
      default:
        return undefined;
    }
  };

  if (typeof window !== 'undefined') {
    // каждый mockTelegramEnv оборачивает прежний прокси — начинаем с чистого
    delete (window as { TelegramWebviewProxy?: unknown }).TelegramWebviewProxy;
  }
  mockTelegramEnv({
    launchParams: {
      tgWebAppVersion: version,
      tgWebAppPlatform: clientPlatform,
      tgWebAppThemeParams: theme,
      tgWebAppData: rawInitData ?? initData(languageCode, startParam),
      ...(startParam ? { tgWebAppStartParam: startParam } : {}),
    } as never,
    onEvent: (event) => {
      const params = event.params as Payload | undefined;
      calls.push({ name: event.name, params });
      handle(event.name, params);
    },
    resetPostMessage: true,
  });

  const telegram: MockTelegram = {
    calls,
    callsOf: (name) => calls.filter((c) => c.name === name).map((c) => c.params),
    emit,
    setColorScheme(scheme) {
      theme = MOCK_THEMES[scheme];
      emit('theme_changed', { theme_params: theme });
    },
  };
  return { platform: createTmaPlatform('mock'), telegram };
}
