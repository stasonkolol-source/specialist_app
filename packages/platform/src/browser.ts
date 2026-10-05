// Браузер (веб-оболочка 8.1 и разработка без Telegram): MainButton и «назад» рисуются в контенте —
// оболочка приложения (useBottomButtonState, useBackButtonState); «назад» самого браузера — обычная
// история, за ней следует роутер. «Поделиться» — navigator.share или копирование, хранилище —
// localStorage.
import { Listeners, createBottomButton } from './button.ts';
import { browserLocation } from './location.ts';
import type { ColorScheme, Insets, KeyValueStorage, Platform } from './types.ts';
import { capabilitiesFor } from './version.ts';

const ZERO: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

function localStorageKV(prefix: string): KeyValueStorage {
  const key = (k: string) => `${prefix}${k}`;
  return {
    get: async (k) => {
      try {
        return window.localStorage.getItem(key(k));
      } catch {
        return null;
      }
    },
    set: async (k, v) => {
      try {
        window.localStorage.setItem(key(k), v);
      } catch {
        // приватный режим: хранилище недоступно
      }
    },
    remove: async (k) => {
      try {
        window.localStorage.removeItem(key(k));
      } catch {
        // приватный режим: хранилище недоступно
      }
    },
  };
}

export function createBrowserPlatform(): Platform {
  const media = window.matchMedia?.('(prefers-color-scheme: dark)');
  const scheme = (): ColorScheme => (media?.matches ? 'dark' : 'light');
  const themeListeners = new Listeners<[ColorScheme]>();
  media?.addEventListener?.('change', () => themeListeners.emit(scheme()));

  const viewportListeners = new Listeners();
  window.addEventListener('resize', () => viewportListeners.emit());

  const params = new URLSearchParams(window.location.search);

  return {
    kind: 'browser',
    launch: {
      platform: 'browser',
      version: '0',
      rawInitData: null,
      startParam: params.get('startapp'),
      languageCode: null,
    },
    capabilities: capabilitiesFor('0'),
    isVersionAtLeast: () => false,
    ready: () => {},
    expand: () => {},
    close: () => window.history.back(),
    theme: {
      colorScheme: scheme,
      onChange: (listener) => themeListeners.add(listener),
      setHeaderColor: () => {},
      setBackgroundColor: () => {},
      setBottomBarColor: () => {},
    },
    viewport: {
      stableHeight: () => window.innerHeight,
      safeArea: () => ZERO,
      contentSafeArea: () => ZERO,
      onChange: (listener) => viewportListeners.add(listener),
    },
    // своя кнопка «назад» — в контенте (её нажатие обрабатывает стек «назад» в react.tsx). Пустая
    // запись в истории, чтобы «назад» браузера попадал в приложение, ломала историю роутера
    backButton: {
      native: false,
      setVisible: () => {},
      onClick: () => () => {},
    },
    mainButton: createBottomButton(false),
    secondaryButton: createBottomButton(false),
    haptics: {
      impact: () => navigator.vibrate?.(10),
      notification: () => navigator.vibrate?.(20),
      selection: () => {},
    },
    popup: async ({ title, message, buttons }) => {
      const text = title ? `${title}\n\n${message}` : message;
      if (!buttons || buttons.length <= 1) {
        window.alert(text);
        return buttons?.[0]?.id ?? 'ok';
      }
      return window.confirm(text) ? (buttons[0]?.id ?? null) : null;
    },
    confirm: async (message) => window.confirm(message),
    setClosingConfirmation: (enabled) => {
      window.onbeforeunload = enabled ? (e) => e.preventDefault() : null;
    },
    setVerticalSwipes: () => {},
    requestWriteAccess: async () => false,
    requestContact: async () => false,
    shareContact: async () => null,
    shareMessage: async () => false,
    shareLink: async (url, text) => {
      try {
        if (navigator.share) {
          await navigator.share({ url, ...(text ? { text } : {}) });
          return 'shared';
        }
        await navigator.clipboard.writeText(url);
        return 'copied';
      } catch {
        return 'failed';
      }
    },
    openLink: (url) => {
      window.open(url, '_blank', 'noopener');
    },
    openTelegramLink: (url) => {
      window.open(url, '_blank', 'noopener');
    },
    storage: { device: localStorageKV('sosed:'), cloud: localStorageKV('sosed:cloud:') },
    location: { get: browserLocation },
  };
}
