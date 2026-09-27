import { describe, expect, it } from 'vitest';

import { cyrToLat } from './translit.ts';

describe('транслитерация sr-Cyrl → sr-Latn', () => {
  it.each([
    ['Љубав', 'Ljubav'],
    ['ЉУБАВ', 'LJUBAV'],
    ['Њива', 'Njiva'],
    ['ЊИВА', 'NJIVA'],
    ['Џеп', 'Džep'],
    ['ЏЕП', 'DŽEP'],
    ['Љ', 'Lj'],
    ['ПЉ', 'PLJ'],
    ['коњ', 'konj'],
    ['Ђорђе Ћирић', 'Đorđe Ćirić'],
    ['Чачак, Шабац, Жабаљ', 'Čačak, Šabac, Žabalj'],
    ['инјекција', 'injekcija'],
    ['Мајстори у близини', 'Majstori u blizini'],
  ])('%s → %s', (cyr, lat) => {
    expect(cyrToLat(cyr)).toBe(lat);
  });

  it('латиница, цифры, ICU-синтаксис и нерусские символы не меняются', () => {
    const icu = '{count, plural, one {# утисак} other {# утисака}} · 5 000 RSD';
    expect(cyrToLat(icu)).toBe('{count, plural, one {# utisak} other {# utisaka}} · 5 000 RSD');
  });
});
