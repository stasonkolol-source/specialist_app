// Общий ESLint (flat config) по ADR-0020 §13.
// Использование в пакете: `export default sosed({ react: true, i18n: true })`.
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import { appBoundaries as appBoundariesRule } from './app-boundaries.js';
import { noJsxLiteral } from './no-jsx-literal.js';
import { radiusTokens } from './radius-tokens.js';

// Свои правила — один объект плагина: flat config не даёт привязать ключ `sosed` к разным объектам,
// а блоки i18n и границ в apps/tma включены вместе
const sosedPlugin = {
  rules: {
    'no-jsx-literal': noJsxLiteral,
    'app-boundaries': appBoundariesRule,
    'radius-tokens': radiusTokens,
  },
};

const apiOnly = {
  group: ['axios', 'ky', 'ofetch', 'node-fetch', 'undici'],
  message: 'API — только хуки packages/api-client',
};
const tmaOnly = {
  group: ['@tma.js/*'],
  message: 'Telegram — только через packages/platform',
};
// Импорт каталога (`../deals`) sosed/app-boundaries не относит ни к одной фиче и пропускает —
// через него обходились бы границы routes → features. Поэтому путь — всегда до файла.
const explicitFile = {
  regex: '^\\.{1,2}/(?:(?!\\.(?:ts|tsx|js|mjs|css|json)$).)*$',
  message: 'Относительный импорт — до файла с расширением (./x.ts, ./dir/index.ts)',
};

/**
 * @param {object} [options]
 * @param {boolean} [options.react] — правила хуков React
 * @param {boolean} [options.i18n] — литералы в JSX запрещены (только t())
 * @param {boolean} [options.allowTma] — только для packages/platform
 * @param {string[]} [options.allowFetchIn] — файлы, где разрешён fetch (mutator api-client)
 * @param {boolean} [options.appBoundaries] — границы routes → features → packages (apps/tma),
 *   правило sosed/app-boundaries
 * @param {string[]} [options.radii] — токены радиусов (ключи radius из design-tokens/tokens.json):
 *   в классах rounded-* только они, правило sosed/radius-tokens (пакеты с Tailwind)
 * @param {string} [options.root] — каталог пакета (import.meta.dirname): typescript-eslint ищет tsconfig
 *   от него, иначе в одном процессе с несколькими пакетами (IDE, тесты) не может выбрать корень
 */
export function sosed({
  root,
  react = false,
  i18n = false,
  allowTma = false,
  allowFetchIn = [],
  appBoundaries = false,
  radii,
} = {}) {
  const configs = [
    {
      ignores: [
        '**/dist/**',
        '**/dist-*/**',
        '**/coverage/**',
        '**/node_modules/**',
        '**/*.generated.*',
        '**/test-results/**',
        '**/playwright-report/**',
      ],
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
      languageOptions: {
        globals: { ...globals.browser, ...globals.es2023 },
        ...(root ? { parserOptions: { tsconfigRootDir: root } } : {}),
      },
      rules: {
        'no-restricted-imports': [
          'error',
          { patterns: allowTma ? [apiOnly, explicitFile] : [tmaOnly, apiOnly, explicitFile] },
        ],
        'no-restricted-globals': [
          'error',
          { name: 'fetch', message: 'API — только хуки packages/api-client' },
        ],
        '@typescript-eslint/no-explicit-any': 'error',
        '@typescript-eslint/consistent-type-imports': 'error',
        '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      },
    },
  ];
  if (allowFetchIn.length > 0) {
    configs.push({ files: allowFetchIn, rules: { 'no-restricted-globals': 'off' } });
  }
  if (react) {
    configs.push({
      plugins: { 'react-hooks': reactHooks },
      rules: reactHooks.configs.recommended.rules,
    });
  }
  if (i18n) {
    configs.push({
      files: ['**/*.tsx'],
      plugins: { sosed: sosedPlugin },
      rules: { 'sosed/no-jsx-literal': 'error' },
    });
  }
  if (appBoundaries) {
    configs.push({
      files: ['src/**/*.{ts,tsx}'],
      plugins: { sosed: sosedPlugin },
      rules: { 'sosed/app-boundaries': ['error', root ? { root } : {}] },
    });
  }
  if (radii) {
    configs.push({
      files: ['**/*.{ts,tsx}'],
      plugins: { sosed: sosedPlugin },
      rules: { 'sosed/radius-tokens': ['error', { tokens: radii }] },
    });
  }
  // Тесты, конфиги и скрипты сборки: литералы и fetch допустимы
  configs.push({
    files: ['**/*.test.{ts,tsx}', '**/scripts/**', '**/*.config.{ts,js,mjs}'],
    languageOptions: { globals: { ...globals.node } },
    rules: {
      'no-restricted-globals': 'off',
      // тексты в тестах — данные фикстур, а не интерфейс
      ...(i18n ? { 'sosed/no-jsx-literal': 'off' } : {}),
    },
  });
  return configs;
}

export default sosed;
