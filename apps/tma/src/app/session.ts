// Вход Mini App (ADR-0009): initData из launch params → POST /auth/telegram → токены в памяти.
// Тот же обмен — колбэк onReauth api-client, когда refresh не помог (сессия отозвана или истекла).
import { identityAuthenticateTelegram, setSession } from '@sosed/api-client';
import type { Platform } from '@sosed/platform';

export interface Auth {
  /** true — сессия есть: вход по initData удался. Параллельные вызовы делят один запрос. */
  signIn(): Promise<boolean>;
}

export function createAuth(platform: Platform): Auth {
  let pending: Promise<boolean> | null = null;

  const exchange = async (): Promise<boolean> => {
    const initData = platform.launch.rawInitData;
    if (!initData) return false; // браузер без Telegram: вход появится с кнопкой «Войти» (этап 2)
    try {
      const auth = await identityAuthenticateTelegram({ authorization: `tma ${initData}` });
      setSession({ accessToken: auth.access_token, refreshToken: auth.refresh_token });
      return true;
    } catch {
      setSession(null);
      return false;
    }
  };

  return {
    signIn() {
      pending ??= exchange().finally(() => {
        pending = null;
      });
      return pending;
    },
  };
}
