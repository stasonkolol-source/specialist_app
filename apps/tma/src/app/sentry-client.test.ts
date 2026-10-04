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
});
