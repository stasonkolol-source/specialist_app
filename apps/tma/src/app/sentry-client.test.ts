import { captureException, close, createTransport, flush, init } from '@sentry/react';
import { afterEach, describe, expect, it } from 'vitest';

import { scrubText, sentryOptions } from './sentry-client.ts';

// initData из hash запуска Telegram: query_id, user (id 279058397, имя), auth_date, hash
const INIT_DATA =
  'query_id%3DAAHdF6IQAAAAAN0XohDhrOrc%26user%3D%257B%2522id%2522%253A279058397%252C' +
  '%2522first_name%2522%253A%2522Vladislav%2522%257D%26auth_date%3D1662771648' +
  '%26hash%3Dc501b71e775f74ce10e377dea85a7ea2';
const LAUNCH = `#tgWebAppData=${INIT_DATA}&tgWebAppVersion=7.10&tgWebAppPlatform=ios`;
const SECRETS = ['AAHdF6IQ', '279058397', 'Vladislav', '1662771648', 'c501b71e'];
// приглашение на отзыв (S56): uuid ссылки и тот же id в коде startapp `ri_<base62>`
const INVITE = '4b7f0f1e-9c3a-4d2b-8e6f-1a2b3c4d5e6f';
const INVITE_CODE = 'ri_0123456789ABCDEFGHIJkl';

describe('Sentry: initData never leaves the client', () => {
  afterEach(async () => {
    await close();
    history.replaceState(null, '', '/');
  });

  it('scrubs launch params in hash, query, encoded URLs and raw initData', () => {
    const raw = decodeURIComponent(INIT_DATA);
    for (const text of [
      `https://app.example/${LAUNCH}`,
      `https://app.example/?initData=${INIT_DATA}#/`,
      `/?next=${encodeURIComponent(`/${LAUNCH}`)}`,
      `login failed: ${raw}`,
    ]) {
      const clean = scrubText(text);
      for (const secret of SECRETS) expect(clean).not.toContain(secret);
    }
    // остальное в адресе — как было: версия клиента и платформа помогают разбирать ошибки
    expect(scrubText(`https://app.example/${LAUNCH}`)).toBe(
      'https://app.example/#tgWebAppData=[Filtered]&tgWebAppVersion=7.10&tgWebAppPlatform=ios',
    );
    expect(scrubText('https://app.example/#/jobs/1?tab=responses')).toBe(
      'https://app.example/#/jobs/1?tab=responses',
    );
  });

  it('sends release and environment but no initData in url, breadcrumbs, errors', async () => {
    const sent: string[] = [];
    // вход не удался: hash запуска остался в адресе
    history.replaceState(null, '', `/${LAUNCH}`);
    init({
      ...sentryOptions('https://publickey@o4500.ingest.de.sentry.io/4501'),
      transport: (options) =>
        createTransport(options, (request) => {
          const body = request.body;
          sent.push(typeof body === 'string' ? body : new TextDecoder().decode(body));
          return Promise.resolve({ statusCode: 200 });
        }),
    });
    // крошка navigation: from — адрес с initData; потом снова он — request.url события
    history.replaceState(null, '', '/#/');
    history.replaceState(null, '', `/${LAUNCH}`);
    captureException(new Error(`route not found: ${location.href}`));
    await flush(2000);

    const all = sent.join('\n');
    expect(all).toContain('"type":"event"');
    expect(all).toContain('"category":"navigation"');
    expect(all).toContain('tgWebAppData=[Filtered]');
    // релиз и окружение без переменных сборки — dev (на stage и prod их задаёт deploy.yml)
    expect(all).toContain('"release":"dev"');
    expect(all).toContain('"environment":"dev"');
    for (const secret of SECRETS) expect(all).not.toContain(secret);
  });

  it('hides review-invite tokens: route, API path, encoded address, startapp code', () => {
    expect(scrubText(`https://app.example/#/review-invites/${INVITE}`)).toBe(
      'https://app.example/#/review-invites/[Filtered]',
    );
    expect(scrubText(`GET https://api.example/api/v1/review-invites/${INVITE}?x=1`)).toBe(
      'GET https://api.example/api/v1/review-invites/[Filtered]?x=1',
    );
    expect(scrubText(`/?next=${encodeURIComponent(`/review-invites/${INVITE}`)}`)).toBe(
      '/?next=%2Freview-invites%2F[Filtered]',
    );
    expect(scrubText(`#tgWebAppStartParam=${INVITE_CODE}_rAB&tgWebAppVersion=7.10`)).toBe(
      '#tgWebAppStartParam=ri_[Filtered]_rAB&tgWebAppVersion=7.10',
    );
    expect(scrubText(`?startapp%3D${INVITE_CODE}`)).toBe('?startapp%3Dri_[Filtered]');
    // список своих приглашений и прочие адреса — как были
    expect(scrubText('https://app.example/#/cabinet/review-invites')).toBe(
      'https://app.example/#/cabinet/review-invites',
    );
    expect(scrubText('trip_0123456789ABCDEFGHIJkl')).toBe('trip_0123456789ABCDEFGHIJkl');
  });

  it('sends no review-invite token in breadcrumbs, request url or errors', async () => {
    const sent: string[] = [];
    history.replaceState(null, '', '/#/');
    init({
      ...sentryOptions('https://publickey@o4500.ingest.de.sentry.io/4501'),
      transport: (options) =>
        createTransport(options, (request) => {
          const body = request.body;
          sent.push(typeof body === 'string' ? body : new TextDecoder().decode(body));
          return Promise.resolve({ statusCode: 200 });
        }),
    });
    // форма S56 по ссылке: крошка navigation, адрес страницы и текст ошибки с путём API
    history.replaceState(null, '', `/#/review-invites/${INVITE}`);
    captureException(new Error(`GET /api/v1/review-invites/${INVITE} failed: 500`));
    await flush(2000);

    const all = sent.join('\n');
    expect(all).toContain('"type":"event"');
    expect(all).toContain('review-invites/[Filtered]');
    expect(all).not.toContain(INVITE);
  });
});
