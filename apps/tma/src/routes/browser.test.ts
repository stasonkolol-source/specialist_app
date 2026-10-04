import { parseStartParam, uuidToBase62 } from '@sosed/links';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory, createRouter } from '@tanstack/react-router';
import { describe, expect, it } from 'vitest';

import { CARD_PATHS } from '../features/catalog/index.ts';
import { JOBS_PATHS } from '../features/jobs/index.ts';
import { ENTITY_PATHS } from '../features/shell/web/links.ts';
import { BROWSER_ROUTES, browserStart } from './browser.ts';
import { routeTree } from './tree.tsx';

const ID = '0199cc00-0000-7000-8000-000000000001';
const match = (routeId: string, params: Record<string, string> = {}, search = {}) => ({
  routeId,
  params,
  search,
});

describe('браузерная оболочка (8.1)', () => {
  it('карточка S08–S11, заявка S15, веб-ссылки и удаление аккаунта открыты в браузере', () => {
    for (const routeId of BROWSER_ROUTES) expect(browserStart(match(routeId))).toBeNull();
  });

  it('остальное — «Открыть в Telegram» с кодом того же экрана', () => {
    const b62 = uuidToBase62(ID);
    expect(browserStart(match(JOBS_PATHS.respond, { jobId: ID }))).toBe(`j_${b62}`);
    expect(browserStart(match('/jobs/new', {}, { direct: ID }))).toBe(`s_${b62}`);
    expect(browserStart(match('/jobs/new'))).toBe('n');
    expect(browserStart(match('/deals/$dealId/dispute', { dealId: ID }))).toBe(`p_${b62}`);
    expect(browserStart(match('/messages/$conversationId', { conversationId: ID }))).toBe(
      `c_${b62}`,
    );
    expect(browserStart(match('/profile/delete'))).toBe('m_deletion');
    expect(browserStart(match('/'))).toBe('h');
    expect(browserStart(match('__root__'))).toBe('h');
    expect(browserStart(undefined)).toBe('h');
    // битый id в адресе — главная, а не исключение
    expect(browserStart(match(JOBS_PATHS.respond, { jobId: 'nope' }))).toBe('h');
  });

  it('коды разбирает тот же кодек, что у бота', () => {
    const code = browserStart(match(JOBS_PATHS.manage, { jobId: ID }));
    expect(parseStartParam(code)).toEqual({ type: 'job', id: ID });
  });

  it('маршруты оболочки есть в дереве; экраны сущностей — пути фич', () => {
    const router = createRouter({
      routeTree,
      history: createMemoryHistory(),
      context: { queryClient: new QueryClient() },
    });
    for (const routeId of BROWSER_ROUTES) expect(Object.keys(router.routesById)).toContain(routeId);
    expect(ENTITY_PATHS.specialist(ID)).toBe(CARD_PATHS.profile.replace('$profileId', ID));
    expect(ENTITY_PATHS.job(ID)).toBe(JOBS_PATHS.job.replace('$jobId', ID));
  });
});
