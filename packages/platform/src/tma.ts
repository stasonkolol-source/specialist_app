// Адаптер Telegram Mini App на уровне моста @tma.js: postEvent + события. Так работают и методы,
// которых ещё нет в SDK, а проверка версий — своя (version.ts).
import {
  isColorDark,
  on,
  postEvent as sdkPostEvent,
  retrieveLaunchParams,
  retrieveRawInitData,
} from '@tma.js/sdk-react';

import { Listeners, createBottomButton } from './button.ts';
import type {
  BottomButtonState,
  ColorScheme,
  Coordinates,
  Insets,
  KeyValueStorage,
  LaunchInfo,
  Platform,
} from './types.ts';
import { capabilitiesFor, isVersionAtLeast } from './version.ts';

type Payload = Record<string, unknown>;

// Мост типизирован по методам своей версии SDK; новые методы и параметры шлём как есть
const post = sdkPostEvent as unknown as (method: string, params?: Payload) => void;
const listen = on as unknown as (event: string, listener: (payload: Payload) => void) => () => void;

const REQUEST_TIMEOUT_MS = 30_000;
const ZERO: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

let reqSeq = 0;
function reqId(): string {
  reqSeq += 1;
  return `sosed-${Date.now().toString(36)}-${reqSeq}`;
}

/** Вызов метода и ожидание первого подходящего события. */
function request(
  method: string,
  params: Payload | undefined,
  events: string[],
  match: (payload: Payload) => boolean = () => true,
): Promise<{ event: string; payload: Payload }> {
  return new Promise((resolve, reject) => {
    const offs: (() => void)[] = [];
    const done = () => {
      clearTimeout(timer);
      for (const off of offs) off();
    };
    const timer = setTimeout(() => {
      done();
      reject(new Error(`Нет ответа на ${method}`));
    }, REQUEST_TIMEOUT_MS);
    for (const event of events) {
      offs.push(
        listen(event, (payload) => {
          if (!match(payload ?? {})) return;
          done();
          resolve({ event, payload: payload ?? {} });
        }),
      );
    }
    try {
      post(method, params);
    } catch (error) {
      done();
      reject(error as Error);
    }
  });
}

function schemeOf(themeParams: Payload | undefined): ColorScheme {
  const bg = themeParams?.bg_color ?? themeParams?.bgColor;
  return typeof bg === 'string' && isColorDark(bg) ? 'dark' : 'light';
}

function insetsOf(payload: Payload): Insets {
  const n = (k: keyof Insets) => (typeof payload[k] === 'number' ? (payload[k] as number) : 0);
  return { top: n('top'), right: n('right'), bottom: n('bottom'), left: n('left') };
}

function languageOf(rawInitData: string | null): string | null {
  try {
    const user = JSON.parse(
      new URLSearchParams(rawInitData ?? '').get('user') ?? 'null',
    ) as Payload | null;
    return typeof user?.language_code === 'string' ? user.language_code : null;
  } catch {
    return null;
  }
}

/** `startapp` из launch params (ссылки t.me/<bot>?startapp=…), иначе — из адреса страницы:
 *  кнопка web_app в сообщении бота открывает URL как есть, без start_param, поэтому бот кладёт
 *  тот же код в `?startapp=` (DEVELOPMENT_PLAN 1.6). Код — только навигация: атрибуцию backend
 *  берёт из подписанного initData или из /start. */
function startParamOf(lp: Payload): string | null {
  if (typeof lp.tgWebAppStartParam === 'string') return lp.tgWebAppStartParam;
  return new URLSearchParams(window.location.search).get('startapp');
}

function readLaunch(): { launch: LaunchInfo; themeParams: Payload | undefined } {
  const lp = retrieveLaunchParams() as unknown as Payload;
  const rawInitData = retrieveRawInitData() ?? null;
  const languageCode = languageOf(rawInitData);
  return {
    launch: {
      platform: String(lp.tgWebAppPlatform ?? 'unknown'),
      version: String(lp.tgWebAppVersion ?? '6.0'),
      rawInitData,
      startParam: startParamOf(lp),
      languageCode,
    },
    themeParams: lp.tgWebAppThemeParams as Payload | undefined,
  };
}

function buttonParams(s: BottomButtonState): Payload {
  return {
    is_visible: s.visible,
    is_active: s.enabled,
    is_progress_visible: s.loading,
    text: s.text,
    ...(s.color ? { color: s.color } : {}),
    ...(s.textColor ? { text_color: s.textColor } : {}),
    ...(s.shine !== undefined ? { has_shine_effect: s.shine } : {}),
    ...(s.position ? { position: s.position } : {}),
  };
}

export function createTmaPlatform(kind: 'tma' | 'mock' = 'tma'): Platform {
  const { launch, themeParams } = readLaunch();
  const capabilities = capabilitiesFor(launch.version);
  const atLeast = (v: string) => isVersionAtLeast(launch.version, v);

  let scheme = schemeOf(themeParams);
  const themeListeners = new Listeners<[ColorScheme]>();
  listen('theme_changed', (payload) => {
    scheme = schemeOf(payload.theme_params as Payload | undefined);
    themeListeners.emit(scheme);
  });

  let stableHeight = typeof window === 'undefined' ? 0 : window.innerHeight;
  let safeArea = ZERO;
  let contentSafeArea = ZERO;
  const viewportListeners = new Listeners();
  listen('viewport_changed', (p) => {
    if (p.is_state_stable === true && typeof p.height === 'number') stableHeight = p.height;
    viewportListeners.emit();
  });
  listen('safe_area_changed', (p) => {
    safeArea = insetsOf(p);
    viewportListeners.emit();
  });
  listen('content_safe_area_changed', (p) => {
    contentSafeArea = insetsOf(p);
    viewportListeners.emit();
  });

  const mainButton = createBottomButton(true, (s) =>
    post('web_app_setup_main_button', buttonParams(s)),
  );
  listen('main_button_pressed', () => mainButton.press());
  const secondaryButton = createBottomButton(capabilities.secondaryButton, (s) => {
    if (capabilities.secondaryButton) post('web_app_setup_secondary_button', buttonParams(s));
  });
  listen('secondary_button_pressed', () => secondaryButton.press());

  const backClicks = new Listeners();
  listen('back_button_pressed', () => backClicks.emit());

  const custom = async (method: string, params: Payload): Promise<unknown> => {
    const id = reqId();
    const { payload } = await request(
      'web_app_invoke_custom_method',
      { req_id: id, method, params },
      ['custom_method_invoked'],
      (p) => p.req_id === id,
    );
    if (payload.error) throw new Error(String(payload.error));
    return payload.result;
  };

  const cloud: KeyValueStorage = {
    async get(key) {
      const result = (await custom('getStorageValues', { keys: [key] })) as Payload | undefined;
      const value = result?.[key];
      return typeof value === 'string' && value !== '' ? value : null;
    },
    async set(key, value) {
      await custom('saveStorageValue', { key, value });
    },
    async remove(key) {
      await custom('deleteStorageValues', { keys: [key] });
    },
  };

  const deviceCall = async (method: string, params: Payload, ok: string): Promise<Payload> => {
    const id = reqId();
    const { event, payload } = await request(
      method,
      { req_id: id, ...params },
      [ok, 'device_storage_failed'],
      (p) => p.req_id === id,
    );
    if (event === 'device_storage_failed')
      throw new Error(String(payload.error ?? 'device storage'));
    return payload;
  };
  const deviceStorage: KeyValueStorage = {
    async get(key) {
      const p = await deviceCall(
        'web_app_device_storage_get_key',
        { key },
        'device_storage_key_received',
      );
      return typeof p.value === 'string' ? p.value : null;
    },
    async set(key, value) {
      await deviceCall(
        'web_app_device_storage_save_key',
        { key, value },
        'device_storage_key_saved',
      );
    },
    async remove(key) {
      await deviceCall(
        'web_app_device_storage_save_key',
        { key, value: null },
        'device_storage_key_saved',
      );
    },
  };

  const popup = async (params: { title?: string; message: string; buttons?: Payload[] }) => {
    const { payload } = await request(
      'web_app_open_popup',
      {
        title: params.title ?? '',
        message: params.message,
        buttons: params.buttons ?? [{ id: 'ok', type: 'ok' }],
      },
      ['popup_closed'],
    );
    return typeof payload.button_id === 'string' && payload.button_id !== ''
      ? payload.button_id
      : null;
  };

  const status = async (method: string, event: string, success: string) => {
    const { payload } = await request(method, undefined, [event]);
    return payload.status === success;
  };

  // Первичные значения темы, вьюпорта и safe area: клиент ответит событиями выше
  post('web_app_request_theme');
  post('web_app_request_viewport');
  if (capabilities.safeArea) {
    post('web_app_request_safe_area');
    post('web_app_request_content_safe_area');
  }

  return {
    kind,
    launch,
    capabilities,
    isVersionAtLeast: atLeast,
    ready: () => post('web_app_ready'),
    expand: () => post('web_app_expand'),
    close: () => post('web_app_close'),
    theme: {
      colorScheme: () => scheme,
      onChange: (listener) => themeListeners.add(listener),
      setHeaderColor: (color) => {
        if (atLeast('6.9')) post('web_app_set_header_color', { color });
      },
      setBackgroundColor: (color) => {
        if (atLeast('6.1')) post('web_app_set_background_color', { color });
      },
      setBottomBarColor: (color) => {
        if (capabilities.bottomBarColor) post('web_app_set_bottom_bar_color', { color });
      },
    },
    viewport: {
      stableHeight: () => stableHeight,
      safeArea: () => safeArea,
      contentSafeArea: () => contentSafeArea,
      onChange: (listener) => viewportListeners.add(listener),
    },
    backButton: {
      native: true,
      setVisible: (visible) => post('web_app_setup_back_button', { is_visible: visible }),
      onClick: (listener) => backClicks.add(listener),
    },
    mainButton,
    secondaryButton,
    haptics: {
      impact: (style) => {
        if (capabilities.haptics)
          post('web_app_trigger_haptic_feedback', { type: 'impact', impact_style: style });
      },
      notification: (type) => {
        if (capabilities.haptics)
          post('web_app_trigger_haptic_feedback', {
            type: 'notification',
            notification_type: type,
          });
      },
      selection: () => {
        if (capabilities.haptics)
          post('web_app_trigger_haptic_feedback', { type: 'selection_change' });
      },
    },
    popup: (params) => popup({ ...params, buttons: params.buttons as Payload[] | undefined }),
    confirm: async (message) =>
      (await popup({
        message,
        buttons: [
          { id: 'ok', type: 'ok' },
          { id: 'cancel', type: 'cancel' },
        ],
      })) === 'ok',
    setClosingConfirmation: (enabled) => {
      if (capabilities.closingConfirmation)
        post('web_app_setup_closing_behavior', { need_confirmation: enabled });
    },
    setVerticalSwipes: (enabled) => {
      if (capabilities.verticalSwipes)
        post('web_app_setup_swipe_behavior', { allow_vertical_swipe: enabled });
    },
    requestWriteAccess: () =>
      capabilities.requestWriteAccess
        ? status('web_app_request_write_access', 'write_access_requested', 'allowed')
        : Promise.resolve(false),
    requestContact: () =>
      capabilities.requestContact
        ? status('web_app_request_phone', 'phone_requested', 'sent')
        : Promise.resolve(false),
    shareMessage: async (id) => {
      if (!capabilities.shareMessage) return false;
      const { event } = await request('web_app_send_prepared_message', { id }, [
        'prepared_message_sent',
        'prepared_message_failed',
      ]);
      return event === 'prepared_message_sent';
    },
    shareLink: async (url, text) => {
      const query = new URLSearchParams({ url, ...(text ? { text } : {}) });
      post('web_app_open_tg_link', { path_full: `/share/url?${query.toString()}` });
      return 'shared';
    },
    openLink: (url) => post('web_app_open_link', { url }),
    openTelegramLink: (url) => {
      const path = url.replace(/^https?:\/\/t\.me/, '');
      post('web_app_open_tg_link', { path_full: path });
    },
    storage: {
      device: capabilities.deviceStorage ? deviceStorage : cloud,
      cloud,
    },
    location: {
      request: async (): Promise<Coordinates | null> => {
        if (!capabilities.location) return null;
        const checked = await request('web_app_check_location', undefined, ['location_checked']);
        if (checked.payload.available !== true) return null;
        const { payload } = await request('web_app_request_location', undefined, [
          'location_requested',
        ]);
        if (
          payload.available !== true ||
          typeof payload.latitude !== 'number' ||
          typeof payload.longitude !== 'number'
        ) {
          return null;
        }
        return {
          latitude: payload.latitude,
          longitude: payload.longitude,
          ...(typeof payload.horizontal_accuracy === 'number'
            ? { accuracy: payload.horizontal_accuracy }
            : {}),
        };
      },
    },
  };
}
