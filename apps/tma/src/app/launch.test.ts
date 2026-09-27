import { describe, expect, it } from 'vitest';

import { launchHref, openedByTelegram } from './launch.ts';

const DONE = { home_city_id: 1, intent: 'client', consent_required: false } as const;
const NEW = { home_city_id: null, intent: null, consent_required: true } as const;
const OUTDATED = { ...DONE, consent_required: true } as const;

/** Адрес при запуске из Telegram: в hash — launch params, путь роутера — не «/…». */
const TELEGRAM_LAUNCH = {
  pathname: 'tgWebAppData=user%3D1&tgWebAppVersion=9.1',
  href: 'tgWebAppData=user%3D1&tgWebAppVersion=9.1',
  search: '',
};
const at = (href: string) => {
  const [pathname = '/', search = ''] = href.split('?');
  return { pathname, href, search: search ? `?${search}` : '' };
};

describe('launchHref', () => {
  it('starts a new user with S02a and keeps the deep link target for after it', () => {
    expect(launchHref(NEW, at('/'), null)).toBe('/onboarding/language');
    expect(launchHref(NEW, TELEGRAM_LAUNCH, '/jobs/new')).toBe(
      '/onboarding/language?next=%2Fjobs%2Fnew',
    );
  });

  it('shows only S02c to a returning user after a new legal version', () => {
    expect(launchHref(OUTDATED, at('/'), null)).toBe('/onboarding/rules');
  });

  it('opens home or the deep link target for an onboarded user', () => {
    expect(launchHref(DONE, TELEGRAM_LAUNCH, null)).toBe('/');
    expect(launchHref(DONE, at('/'), null)).toBeNull();
    expect(launchHref(DONE, at('/'), '/jobs/new')).toBe('/jobs/new');
  });

  it('keeps a screen reopened inside the client (reload)', () => {
    expect(launchHref(DONE, at('/profile'), null)).toBeNull();
    expect(launchHref(NEW, at('/profile'), null)).toBe('/onboarding/language?next=%2Fprofile');
  });

  it('resumes the onboarding on reload and leaves it once it is done', () => {
    const intent = at('/onboarding/intent?next=%2Fprofile');
    expect(launchHref({ ...NEW, home_city_id: 1 }, intent, null)).toBeNull();
    expect(launchHref(DONE, intent, null)).toBe('/profile');
    expect(launchHref(DONE, at('/onboarding/rules?next=https%3A%2F%2Fevil.example'), null)).toBe(
      '/',
    );
  });

  it('lets a guest browse: no onboarding, onboarding addresses lead home', () => {
    expect(launchHref(null, at('/'), null)).toBeNull();
    expect(launchHref(null, at('/onboarding/language'), null)).toBe('/');
    expect(launchHref(null, TELEGRAM_LAUNCH, null)).toBe('/');
  });
});

describe('openedByTelegram', () => {
  it('tells a launch from Telegram from a reload inside the client', () => {
    expect(openedByTelegram('tma', '#tgWebAppData=user%3D1&tgWebAppVersion=9.1')).toBe(true);
    expect(openedByTelegram('tma', '#tgWebAppVersion=9.1&tgWebAppPlatform=ios')).toBe(true);
    expect(openedByTelegram('tma', '#/profile')).toBe(false);
    expect(openedByTelegram('tma', '')).toBe(false);
    expect(openedByTelegram('mock', '')).toBe(true);
  });
});
