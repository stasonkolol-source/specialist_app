// Правила ADR-0020 §13 действительно срабатывают: линтим код с конфигами пакетов.
import { fileURLToPath } from 'node:url';

import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

import { sosed } from '../eslint.js';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const fixture = fileURLToPath(new URL('./fixture-app/', import.meta.url));

async function messages(cwd, filePath, code, overrideConfig) {
  const eslint = new ESLint({
    cwd,
    ...(overrideConfig ? { overrideConfigFile: true, overrideConfig } : {}),
  });
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages;
}

async function rules(cwd, filePath, code, overrideConfig) {
  return (await messages(cwd, filePath, code, overrideConfig)).map((m) => m.ruleId);
}

describe('apps/tma', () => {
  const tma = `${root}apps/tma`;

  it('прямой импорт @tma.js/* запрещён', async () => {
    const code = "import { init } from '@tma.js/sdk-react';\nexport const x = init;\n";
    expect(await rules(tma, 'src/app/main.ts', code)).toContain('no-restricted-imports');
  });

  it('HTTP-клиенты и fetch — только в api-client', async () => {
    expect(
      await rules(tma, 'src/app/a.ts', "import ky from 'ky';\nexport const k = ky;\n"),
    ).toContain('no-restricted-imports');
    expect(await rules(tma, 'src/app/b.ts', "export const r = fetch('/x');\n")).toContain(
      'no-restricted-globals',
    );
  });

  it('литерал в JSX запрещён — только t()', async () => {
    const code = 'export const C = () => <p>Привет</p>;\n';
    expect(await rules(tma, 'src/app/C.tsx', code)).toContain('sosed/no-jsx-literal');
  });
});

describe('packages/platform', () => {
  it('единственное место, где разрешён @tma.js', async () => {
    const code = "import { isTMA } from '@tma.js/sdk-react';\nexport const x = isTMA;\n";
    expect(await rules(`${root}packages/platform`, 'src/x.ts', code)).toEqual([]);
  });
});

describe('границы routes → features → packages', () => {
  const config = sosed({ root: fixture, react: true, appBoundaries: true });
  const lint = (filePath, code) => rules(fixture, filePath, code, config);

  it('фича не импортирует другую фичу', async () => {
    const code = "import { deals } from '../deals/index.ts';\nexport const x = deals;\n";
    const found = await messages(fixture, 'src/features/jobs/index.ts', code, config);
    expect(found.map((m) => [m.ruleId, m.message])).toContainEqual([
      'sosed/app-boundaries',
      'Фича jobs не импортирует фичу deals: общее — в packages/hooks или ui-web',
    ]);
  });

  it.each([
    [
      'import type',
      "import type { deals } from '../deals/index.ts';\nexport type D = typeof deals;\n",
    ],
    ['export * from', "export * from '../deals/index.ts';\n"],
    ['import()', "export const load = () => import('../deals/index.ts');\n"],
  ])('и через %s', async (_, code) => {
    expect(await lint('src/features/jobs/index.ts', code)).toContain('sosed/app-boundaries');
  });

  it('routes импортируют фичи', async () => {
    const code = "import { jobs } from '../features/jobs/index.ts';\nexport const x = jobs;\n";
    expect(await lint('src/routes/jobs.ts', code)).toEqual([]);
  });

  it('app импортирует фичи', async () => {
    const code = "import { jobs } from '../features/jobs/index.ts';\nexport const x = jobs;\n";
    expect(await lint('src/app/router.ts', code)).toEqual([]);
  });

  it('routes не импортируют app', async () => {
    const code = "import { router } from '../app/router.ts';\nexport const x = router;\n";
    expect(await lint('src/routes/jobs.ts', code)).toContain('sosed/app-boundaries');
  });

  it('экран импортирует модули своей группы фич', async () => {
    const code = "import { jobs } from '../index.ts';\nexport const x = jobs;\n";
    expect(await lint('src/features/jobs/s22-my-jobs/Screen.ts', code)).toEqual([]);
  });

  it('импорт каталога без файла запрещён: иначе границы не видны', async () => {
    const code = "import { deals } from '../deals';\nexport const x = deals;\n";
    expect(await lint('src/features/jobs/index.ts', code)).toContain('no-restricted-imports');
  });

  it('фича не импортирует routes', async () => {
    const code = "import { route } from '../../routes/jobs.ts';\nexport const x = route;\n";
    expect(await lint('src/features/jobs/index.ts', code)).toContain('sosed/app-boundaries');
  });

  it('файлы вне app, routes и фич (src/testing) не проверяются', async () => {
    const code = "import { jobs } from '../features/jobs/index.ts';\nexport const x = jobs;\n";
    expect(await lint('src/testing/render.ts', code)).toEqual([]);
  });
});

describe('sosed/no-jsx-literal', () => {
  const config = sosed({ root: fixture, react: true, i18n: true });
  const lint = (code) => rules(fixture, 'src/features/jobs/View.tsx', code, config);

  it('ловит текст, строки в {} и текстовые атрибуты', async () => {
    expect(await lint('export const A = () => <p>Hello</p>;\n')).toEqual(['sosed/no-jsx-literal']);
    expect(await lint("export const B = () => <p>{'Текст'}</p>;\n")).toEqual([
      'sosed/no-jsx-literal',
    ]);
    expect(await lint('export const C = () => <img alt="Фото" src="x.png" />;\n')).toEqual([
      'sosed/no-jsx-literal',
    ]);
  });

  it('не трогает t(), знаки, className и Trans', async () => {
    const ok = [
      'declare const t: (k: string) => string;\nexport const A = () => <p className="card">{t(\'a.b\')} · 5</p>;\n',
      'declare const Trans: (p: { children: unknown }) => null;\nexport const B = () => <Trans>Hello</Trans>;\n',
    ];
    for (const code of ok) expect(await lint(code)).toEqual([]);
  });
});
