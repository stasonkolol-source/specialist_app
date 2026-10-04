import { uuidToBase62 } from '@sosed/links';
import { describe, expect, it } from 'vitest';

import { entityId, entityStart, telegramLink } from './links.ts';

const ID = '0199cc00-0000-7000-8000-000000000001';

describe('веб-ссылки (8.1)', () => {
  it('id из адреса — base62, как в коде startapp, или UUID', () => {
    expect(entityId(uuidToBase62(ID))).toBe(ID);
    expect(entityId(ID.toUpperCase())).toBe(ID);
    expect(entityId('not-an-id')).toBeNull();
  });

  it('ссылка на бота — t.me с кодом startapp; без бота — нет', () => {
    const start = entityStart('specialist', ID);
    expect(start).toBe(`s_${uuidToBase62(ID)}`);
    expect(telegramLink(start, 'sosed_bot')).toBe(`https://t.me/sosed_bot?startapp=${start}`);
    expect(telegramLink(start, null)).toBeNull();
  });
});
