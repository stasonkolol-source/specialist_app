// Браузер (веб-оболочка и разработка без Telegram): кнопки рисуются в контенте, «назад» — история браузера,
// «поделиться» — navigator.share или копирование, хранилище — localStorage.
import { Listeners, createBottomButton } from './button.ts';
import type { ColorScheme, Insets, KeyValueStorage, Platform } from './types.ts';
import { capabilitiesFor } from './version.ts';

const ZERO: Insets = { top: 0, right: 0, bottom: 0, left: 0 };
const BACK_STATE = { sosedBack: true };

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

  const backClicks = new Listeners();
  let backVisible = false;
  window.addEventListener('popstate', () => {
    if (backVisible) backClicks.emit();
  });

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
    backButton: {
      native: false,
      setVisible(visible) {
        // «назад» браузера должен попасть в приложение, а не уйти со страницы
        if (visible && !backVisible) window.history.pushState(BACK_STATE, '');
        backVisible = visible;
      },
      onClick: (listener) => backClicks.add(listener),
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
    location: {
      request: () =>
        new Promise((resolve) => {
          if (!navigator.geolocation) {
            resolve(null);
            return;
          }
          navigator.geolocation.getCurrentPosition(
            (pos) =>
              resolve({
                latitude: pos.coords.latitude,
                longitude: pos.coords.longitude,
                accuracy: pos.coords.accuracy,
              }),
            () => resolve(null),
            { timeout: 15_000 },
          );
        }),
    },
  };
}
