// Правила ADR-0020 §13 действительно срабатывают: линтим код с конфигами пакетов.
import { fileURLToPath } from 'node:url';

import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

import { sosed } from '../eslint.js';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const fixture = fileURLToPath(new URL('./fixture-app/', import.meta.url));

async function rules(cwd, filePath, code, overrideConfig) {
  const eslint = new ESLint({
    cwd,
    ...(overrideConfig ? { overrideConfigFile: true, overrideConfig } : {}),
  });
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.map((m) => m.ruleId);
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

  it('фича не импортирует другую фичу', async () => {
    const code = "import { deals } from '../deals/index.ts';\nexport const x = deals;\n";
    expect(await rules(fixture, 'src/features/jobs/index.ts', code, config)).toContain(
      'boundaries/element-types',
    );
  });

  it('routes импортируют фичи', async () => {
    const code = "import { jobs } from '../features/jobs/index.ts';\nexport const x = jobs;\n";
    expect(await rules(fixture, 'src/routes/jobs.ts', code, config)).toEqual([]);
  });

  it('фича не импортирует routes', async () => {
    const code = "import { route } from '../../routes/jobs.ts';\nexport const x = route;\n";
    expect(await rules(fixture, 'src/features/jobs/index.ts', code, config)).toContain(
      'boundaries/element-types',
    );
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
