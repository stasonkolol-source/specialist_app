// Запуск и онбординг (DEVELOPMENT_PLAN 1.5b): S01 → S02a → S02b → S02c → главная для нового
// пользователя, сразу главная для вернувшегося, только S02c после новой редакции правил, deep link,
// охрана создающих действий, загрузка, ошибки и офлайн.
import type { MeOut, MeUpdateIn } from '@sosed/api-client';
import { getIdentityGetMeQueryKey, identityUpdateMe, setSession } from '@sosed/api-client';
import { getIdentityAuthenticateTelegramMockHandler } from '@sosed/api-client/mocks';
import { tokens } from '@sosed/design-tokens';
import { MutationObserver } from '@tanstack/react-query';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, delay, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useOnboardingStore } from '../features/onboarding/shared/store.ts';
import { useSystemStore } from '../features/service/s49-system/index.ts';
import { startApp } from '../testing/app.tsx';
import {
  backButtonVisible,
  mainButton,
  pressBackButton,
  pressMainButton,
  userBackend,
} from '../testing/app.tsx';
import {
  CLIENT_CONFIG,
  ME,
  NEW_USER,
  OUTDATED_CONSENTS_USER,
  citiesFor,
} from '../testing/fixtures.ts';
import { TOKENS, server } from '../testing/msw.ts';

const problem = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  HttpResponse.json(
    { type: 'x', title: code, status, code, trace_id: 'test', ...extra },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );

beforeEach(() => {
  useSystemStore.setState({ appWide: null, restriction: null });
  useOnboardingStore.getState().reset();
});
afterEach(() => {
  setSession(null);
  vi.useRealTimers();
});

/** Дольше gcTime React Query по умолчанию: запись кэша без подписчиков уже была бы удалена. */
const PAST_DEFAULT_GC_MS = 5 * 60_000 + 1;

/** Таймеры React Query (сборка мусора) — поддельные; остальное время идёт как обычно. */
const fakeGcTimers = () =>
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });

const meInCache = (app: ReturnType<typeof startApp>['app']) =>
  app.queryClient.getQueryData<MeOut>(getIdentityGetMeQueryKey());

describe('S01 launch', () => {
  it('shows the wordmark, skeleton and «Входим через Telegram…» until signed in', async () => {
    let release = () => undefined as void;
    const signedIn = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      getIdentityAuthenticateTelegramMockHandler(async () => {
        await signedIn;
        return { ...TOKENS, is_new: false, user: ME };
      }),
    );
    startApp('/');

    expect(await screen.findByRole('heading', { name: 'Соседи', level: 1 })).toBeTruthy();
    expect(screen.getByText('Мастера рядом, на вашем языке')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe('Входим через Telegram…');
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();

    release();
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(screen.queryByText('Входим через Telegram…')).toBeNull();
  });

  it('shows S49a «Нет соединения» when sign-in has no network and retries', async () => {
    let online = false;
    server.use(
      http.post('*/api/v1/auth/telegram', () =>
        online ? HttpResponse.json({ ...TOKENS, is_new: false, user: ME }) : HttpResponse.error(),
      ),
    );
    startApp('/');

    expect(await screen.findByRole('heading', { name: 'Нет соединения' })).toBeTruthy();
    online = true;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
  });

  it('shows «Что-то пошло не так» on a server failure and retries', async () => {
    let failing = true;
    server.use(
      http.post('*/api/v1/auth/telegram', () =>
        failing
          ? problem(500, 'internal_error')
          : HttpResponse.json({ ...TOKENS, is_new: false, user: ME }),
      ),
    );
    startApp('/');

    expect(await screen.findByRole('heading', { name: 'Что-то пошло не так' })).toBeTruthy();
    failing = false;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
  });

  it('lets a guest browse when initData is refused: no onboarding', async () => {
    server.use(http.post('*/api/v1/auth/telegram', () => problem(401, 'invalid_init_data')));
    const { app } = startApp('/onboarding/language');

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/');
  });
});

describe('new user: S02a → S02b → S02c → home', () => {
  it('walks the whole onboarding and lands on the home stub', async () => {
    const backend = userBackend(NEW_USER);
    const { app, telegram } = startApp('/');

    // S02a: язык из Telegram, пилотный город выбран, English и Белград — «скоро»
    expect(await screen.findByRole('heading', { name: 'Язык и город', level: 1 })).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'Шаг 1 из 3' })).toBeTruthy();
    const languages = screen.getByRole('radiogroup', { name: 'Язык интерфейса' });
    expect(within(languages).getByRole('radio', { name: 'Русский' }).ariaChecked).toBe('true');
    const english = within(languages).getByRole('radio', {
      name: 'English',
      description: 'скоро',
    }) as HTMLButtonElement;
    expect(english.disabled).toBe(true);
    const cities = await screen.findByRole('radiogroup', { name: 'Город' });
    expect(
      within(cities).getByRole('radio', { name: 'Нови-Сад', description: 'Пилотный город' })
        .ariaChecked,
    ).toBe('true');
    expect(
      (within(cities).getByRole('radio', { name: 'Белград' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(mainButton(telegram)).toMatchObject({
      is_visible: true,
      text: 'Далее',
      color: tokens.color.light.accent,
    });
    expect(backButtonVisible(telegram)).toBe(false);
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();

    await pressMainButton(telegram);

    // S02b
    expect(await screen.findByRole('heading', { name: 'Что вы хотите?', level: 1 })).toBeTruthy();
    expect(backend.requests.patch).toEqual([{ ui_locale: 'ru', home_city_id: 1 }]);
    expect(screen.getByRole('radio', { name: 'Найти мастера' }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(backButtonVisible(telegram)).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Я специалист' }));
    });
    await pressMainButton(telegram);

    // S02c: без галочки «Начать» не пускает
    expect(await screen.findByRole('heading', { name: 'Правила площадки', level: 1 })).toBeTruthy();
    expect(backend.requests.patch.at(-1)).toEqual({ intent: 'pro' });
    expect(mainButton(telegram)).toMatchObject({ is_visible: true, text: 'Начать' });
    await pressMainButton(telegram);
    const checkbox = screen.getByRole('checkbox', {
      name: 'Мне есть 18 лет, я принимаю правила площадки',
    });
    expect(screen.getByRole('alert').textContent).toBe('Отметьте галочку: без неё начать нельзя');
    expect(checkbox.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(checkbox);
    expect(backend.requests.consents).toEqual([]);

    await act(async () => {
      fireEvent.click(checkbox);
    });
    await pressMainButton(telegram);

    // главная (заглушка до 4.8); согласие с версиями из client-config, разрешение писать
    expect(await screen.findByRole('heading', { name: 'Главная', level: 1 })).toBeTruthy();
    expect(backend.requests.consents).toEqual([
      { terms_version: 'draft-1', privacy_version: 'draft-1' },
    ]);
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
    expect(backend.requests.writeAccess).toBe(1);
    expect(app.router.state.location.pathname).toBe('/');
    expect(screen.getByRole('navigation', { name: 'Разделы' })).toBeTruthy();
    expect(mainButton(telegram)).toMatchObject({ is_visible: false });
  });

  it('switches the language on S02a at once, without a reload, and saves it with «Далее»', async () => {
    const backend = userBackend(NEW_USER);
    const { app, telegram } = startApp('/');
    const latin = await screen.findByRole('radio', { name: 'Srpski · latinica' });
    await screen.findByRole('radio', { name: 'Нови-Сад' });

    await act(async () => {
      fireEvent.click(latin);
    });

    expect(await screen.findByRole('heading', { name: 'Jezik i grad', level: 1 })).toBeTruthy();
    expect(document.documentElement.lang).toBe('sr-Latn');
    // названия городов перечитаны на новом языке
    expect(await screen.findByRole('radio', { name: 'Novi Sad' })).toBeTruthy();
    expect(mainButton(telegram)).toMatchObject({ text: 'Dalje' });
    expect(backend.requests.patch).toEqual([]);

    await pressMainButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Šta želite?', level: 1 })).toBeTruthy();
    expect(backend.requests.patch).toEqual([{ ui_locale: 'sr-Latn', home_city_id: 1 }]);
    expect(app.i18n.language).toBe('sr-Latn');
  });

  it('goes back with the Telegram BackButton and keeps the choices', async () => {
    userBackend(NEW_USER);
    const { telegram } = startApp('/');
    await screen.findByRole('radio', { name: 'Нови-Сад' });
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Что вы хотите?' });
    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Ищу подработку' }));
    });
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Правила площадки' });

    await pressBackButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Что вы хотите?' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Ищу подработку' }).getAttribute('aria-checked')).toBe(
      'true',
    );

    await pressBackButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Язык и город' })).toBeTruthy();
    expect(backButtonVisible(telegram)).toBe(false);
  });

  it('opens the full rules (S48) from S02c and comes back with the tick kept', async () => {
    userBackend({ ...NEW_USER, home_city_id: 1, intent: 'client' });
    const { telegram } = startApp('/');
    const checkbox = await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(checkbox);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Читать правила полностью' }));
    });
    expect(
      await screen.findByText('Редакция draft-1 от 27 сентября 2026', {}, { timeout: 3000 }),
    ).toBeTruthy();
    expect(mainButton(telegram)).toMatchObject({ is_visible: false });

    await pressBackButton(telegram);
    expect(
      (await screen.findByRole('checkbox', { name: /Мне есть 18 лет/ })).getAttribute(
        'aria-checked',
      ),
    ).toBe('true');
  });

  it('does not ask Telegram for write access when notifications are off', async () => {
    const backend = userBackend({ ...NEW_USER, home_city_id: 1, intent: 'client' });
    const { telegram } = startApp('/');
    const checkbox = await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(checkbox);
      fireEvent.click(screen.getByRole('switch', { name: 'Уведомления от бота' }));
    });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(telegram.callsOf('web_app_request_write_access')).toEqual([]);
    expect(backend.requests.writeAccess).toBe(0);
  });

  it('finishes the onboarding when the user declines write access', async () => {
    const backend = userBackend({ ...NEW_USER, home_city_id: 1, intent: 'client' });
    const { telegram } = startApp('/', { writeAccess: false });
    const checkbox = await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(checkbox);
    });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(telegram.callsOf('web_app_request_write_access')).toHaveLength(1);
    expect(backend.requests.writeAccess).toBe(0);
  });

  it('resumes an unfinished onboarding at the missing step', async () => {
    userBackend({ ...NEW_USER, home_city_id: 1 });
    const { telegram } = startApp('/');

    expect(await screen.findByRole('heading', { name: 'Что вы хотите?' })).toBeTruthy();
    // открыли сразу S02b: «Назад» ведёт на S02a
    expect(backButtonVisible(telegram)).toBe(true);
    await pressBackButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Язык и город' })).toBeTruthy();
  });

  it('resumes at S02c with «Back» to S02b to change the intent', async () => {
    userBackend({ ...NEW_USER, home_city_id: 1, intent: 'pro' });
    const { app, telegram } = startApp('/');

    expect(await screen.findByRole('heading', { name: 'Правила площадки' })).toBeTruthy();
    // открыли сразу S02c: истории нет, но это онбординг, а не новая редакция правил
    await waitFor(() => expect(backButtonVisible(telegram)).toBe(true));
    await pressBackButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Что вы хотите?' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Я специалист' }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(app.router.state.location.pathname).toBe('/onboarding/intent');
  });

  it('keeps an onboarded user home after S49 «Повторить» mid-session', async () => {
    const backend = userBackend(NEW_USER);
    const { app, telegram } = startApp('/');
    await screen.findByRole('radio', { name: 'Нови-Сад' });
    await pressMainButton(telegram);
    await screen.findByRole('heading', { name: 'Что вы хотите?' });
    await pressMainButton(telegram);
    const checkbox = await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(checkbox);
    });
    await pressMainButton(telegram);
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();

    // техработы посреди сессии: S49 закрывает приложение вместе с экраном запуска
    let maintenance = true;
    server.use(
      http.get('*/api/v1/me', () =>
        maintenance ? problem(503, 'maintenance') : HttpResponse.json(backend.user),
      ),
    );
    await act(async () => {
      await app.queryClient.refetchQueries({ queryKey: getIdentityGetMeQueryKey() });
    });
    expect(await screen.findByRole('heading', { name: 'Технические работы' })).toBeTruthy();

    maintenance = false;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });

    // итог входа при запуске (новый пользователь) не применяется второй раз
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/');
    expect(meInCache(app)).toMatchObject({
      home_city_id: 1,
      intent: 'client',
      consent_required: false,
    });
    expect(backend.requests.consents).toHaveLength(1);
  });
});

describe('returning users', () => {
  it('go straight home when onboarded with current consents', async () => {
    const backend = userBackend(ME);
    const { app, telegram } = startApp('/');

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/');
    expect(backend.requests.patch).toEqual([]);
    expect(mainButton(telegram)?.is_visible ?? false).toBe(false);
  });

  it('see only S02c after a new legal version, without «Back»', async () => {
    const backend = userBackend(OUTDATED_CONSENTS_USER);
    const { app, telegram } = startApp('/');

    expect(await screen.findByRole('heading', { name: 'Правила площадки' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/onboarding/rules');
    expect(backButtonVisible(telegram)).toBe(false);

    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'));
    });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(backend.requests.patch).toEqual([]);
    expect(backend.requests.consents).toHaveLength(1);
  });

  it('asks to re-read the rules when their version changed while S02c was open', async () => {
    userBackend(OUTDATED_CONSENTS_USER);
    let configReads = 0;
    server.use(
      http.post('*/api/v1/me/consents', () =>
        problem(409, 'legal_version_outdated', { document: 'terms', current: 'draft-2' }),
      ),
      http.get('*/api/v1/client-config', () => {
        configReads += 1;
        return HttpResponse.json(CLIENT_CONFIG);
      }),
    );
    const { telegram } = startApp('/');
    const checkbox = await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(checkbox);
    });
    await pressMainButton(telegram);

    expect(
      await screen.findByText(
        'Правила обновились. Прочитайте новую редакцию и подтвердите ещё раз',
      ),
    ).toBeTruthy();
    expect(checkbox.getAttribute('aria-checked')).toBe('false');
    await waitFor(() => expect(configReads).toBe(2));
  });
});

describe('deep links (startapp)', () => {
  it('open home for targets whose screens are not built yet', async () => {
    userBackend(ME);
    const { app } = startApp('/', { startParam: 'j_02y9UKmeRG6vSNbdsEYkkR_rAB12CD' });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/');
  });

  it('open home for a broken code', async () => {
    userBackend(ME);
    const { app } = startApp('/', { startParam: 'nonsense' });
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/');
  });

  it('keep the target through the onboarding of a new user', async () => {
    userBackend({ ...NEW_USER, home_city_id: 1, intent: 'client' });
    const { app, telegram } = startApp('/jobs/new');
    expect(await screen.findByRole('heading', { name: 'Правила площадки' })).toBeTruthy();
    expect(app.router.state.location.search).toEqual({ next: '/jobs/new' });

    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'));
    });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Создать заявку' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new');
  });
});

describe('creating actions require S02c', () => {
  it('sends a user without current consents from «+» to S02c and back to the form', async () => {
    const backend = userBackend(ME);
    const { app, telegram } = startApp('/');
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    // редакция правил сменилась, пока приложение открыто: перечитанный /me требует согласия
    backend.user = OUTDATED_CONSENTS_USER;
    act(() => {
      app.queryClient.setQueryData(getIdentityGetMeQueryKey(), OUTDATED_CONSENTS_USER);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Создать заявку' }));
    });

    expect(await screen.findByRole('heading', { name: 'Правила площадки' })).toBeTruthy();
    expect(backButtonVisible(telegram)).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox'));
    });
    await pressMainButton(telegram);

    expect(await screen.findByRole('heading', { name: 'Создать заявку' })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/jobs/new');
  });

  it('opens S02c when the server refuses an action with 403 consent_required', async () => {
    userBackend(ME);
    server.use(
      http.patch('*/api/v1/me', () =>
        problem(403, 'consent_required', { documents: ['terms', 'privacy', 'age_18'] }),
      ),
    );
    const { app } = startApp('/profile');
    expect(await screen.findByRole('heading', { name: ME.display_name })).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole('radio', { name: 'Srpski (latinica)' }));
    });

    expect(await screen.findByRole('heading', { name: 'Правила площадки' })).toBeTruthy();
    expect(app.router.state.location.search).toEqual({ next: '/profile' });
  });
});

describe('/me stays cached for the whole session', () => {
  it('returns to S02c after the full rules were read for more than 5 minutes', async () => {
    fakeGcTimers();
    userBackend({ ...NEW_USER, home_city_id: 1, intent: 'client' });
    const { app, telegram } = startApp('/');
    await screen.findByRole('checkbox');
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Читать правила полностью' }));
    });
    expect(
      await screen.findByText('Редакция draft-1 от 27 сентября 2026', {}, { timeout: 3000 }),
    ).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(PAST_DEFAULT_GC_MS);
    });
    await pressBackButton(telegram);

    expect(await screen.findByRole('checkbox', { name: /Мне есть 18 лет/ })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/onboarding/rules');
    expect(screen.queryByRole('navigation', { name: 'Разделы' })).toBeNull();
  });

  it('still sends «+» to S02c after more than 5 minutes on home', async () => {
    fakeGcTimers();
    const backend = userBackend(ME);
    const { app } = startApp('/');
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();
    backend.user = OUTDATED_CONSENTS_USER;
    act(() => {
      app.queryClient.setQueryData(getIdentityGetMeQueryKey(), OUTDATED_CONSENTS_USER);
    });

    act(() => {
      vi.advanceTimersByTime(PAST_DEFAULT_GC_MS);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'Создать заявку' }));
    });

    expect(await screen.findByRole('checkbox', { name: /Мне есть 18 лет/ })).toBeTruthy();
    expect(app.router.state.location.search).toEqual({ next: '/jobs/new' });
  });

  it('still opens S02c on 403 consent_required after more than 5 minutes on home', async () => {
    fakeGcTimers();
    const backend = userBackend(ME);
    server.use(
      http.patch('*/api/v1/me', () =>
        problem(403, 'consent_required', { documents: ['terms', 'privacy', 'age_18'] }),
      ),
    );
    const { app, telegram } = startApp('/');
    expect(await screen.findByRole('heading', { name: 'Главная' })).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(PAST_DEFAULT_GC_MS);
    });
    // пока приложение открыто, вышла новая редакция правил: создающий запрос сервер отклоняет
    backend.user = OUTDATED_CONSENTS_USER;
    await act(async () => {
      const action = new MutationObserver<MeOut, Error, MeUpdateIn>(app.queryClient, {
        mutationFn: (data) => identityUpdateMe(data),
      });
      await action.mutate({ intent: 'pro' }).catch(() => undefined);
    });

    expect(await screen.findByRole('checkbox', { name: /Мне есть 18 лет/ })).toBeTruthy();
    expect(app.router.state.location.pathname).toBe('/onboarding/rules');
    expect(app.router.state.location.search).toEqual({ next: '/' });
    // /me перечитан на S02c: «Назад» — туда, откуда пришли
    await waitFor(() => expect(meInCache(app)?.consent_required).toBe(true));
    expect(backButtonVisible(telegram)).toBe(true);
  });
});

describe('S02 errors', () => {
  it('shows the offline state for cities and reloads them on «Повторить»', async () => {
    userBackend(NEW_USER);
    let online = false;
    server.use(
      http.get('*/api/v1/cities', () =>
        online ? HttpResponse.json(citiesFor('ru')) : HttpResponse.error(),
      ),
    );
    startApp('/');

    expect(await screen.findByRole('status')).toBeTruthy();
    expect(
      await screen.findByText(
        'Нет соединения. Проверьте интернет и попробуйте ещё раз',
        {},
        { timeout: 5000 },
      ),
    ).toBeTruthy();
    online = true;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });
    expect(await screen.findByRole('radio', { name: 'Нови-Сад' })).toBeTruthy();
  }, 10_000);

  it('keeps the choice and explains when saving fails', async () => {
    userBackend(NEW_USER);
    let attempt = 0;
    server.use(
      http.patch('*/api/v1/me', async () => {
        attempt += 1;
        await delay(10);
        return attempt === 1 ? HttpResponse.error() : problem(500, 'internal_error');
      }),
    );
    const { telegram } = startApp('/');
    await screen.findByRole('radio', { name: 'Нови-Сад' });

    await pressMainButton(telegram);
    expect(
      await screen.findByText('Нет соединения. Проверьте интернет и попробуйте ещё раз'),
    ).toBeTruthy();
    await pressMainButton(telegram);
    expect(await screen.findByText('Не получилось сохранить. Попробуйте ещё раз')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Язык и город' })).toBeTruthy();
  });
});
