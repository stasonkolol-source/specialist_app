// Общий ESLint (flat config) по ADR-0020 §13.
// Использование в пакете: `export default sosed({ react: true, i18n: true })`.
import js from '@eslint/js';
import boundaries from 'eslint-plugin-boundaries';
import i18next from 'eslint-plugin-i18next';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const apiOnly = {
  group: ['axios', 'ky', 'ofetch', 'node-fetch', 'undici'],
  message: 'API — только хуки packages/api-client',
};
const tmaOnly = {
  group: ['@tma.js/*'],
  message: 'Telegram — только через packages/platform',
};

/**
 * @param {object} [options]
 * @param {boolean} [options.react] — правила хуков React
 * @param {boolean} [options.i18n] — литералы в JSX запрещены (только t())
 * @param {boolean} [options.allowTma] — только для packages/platform
 * @param {string[]} [options.allowFetchIn] — файлы, где разрешён fetch (mutator api-client)
 * @param {boolean} [options.appBoundaries] — границы routes → features → packages (apps/tma)
 */
export function sosed({
  react = false,
  i18n = false,
  allowTma = false,
  allowFetchIn = [],
  appBoundaries = false,
} = {}) {
  const configs = [
    {
      ignores: [
        '**/dist/**',
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
      languageOptions: { globals: { ...globals.browser, ...globals.es2023 } },
      rules: {
        'no-restricted-imports': ['error', { patterns: allowTma ? [apiOnly] : [tmaOnly, apiOnly] }],
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
      plugins: { i18next },
      rules: { 'i18next/no-literal-string': ['error', { mode: 'jsx-text-only' }] },
    });
  }
  if (appBoundaries) {
    configs.push({
      files: ['src/**/*.{ts,tsx}'],
      plugins: { boundaries },
      settings: {
        'boundaries/elements': [
          { type: 'app', pattern: 'src/app/**' },
          { type: 'routes', pattern: 'src/routes/**' },
          { type: 'feature', pattern: 'src/features/*/**', capture: ['feature'] },
        ],
      },
      rules: {
        'boundaries/element-types': [
          'error',
          {
            default: 'disallow',
            rules: [
              { from: 'app', allow: ['app', 'routes', 'feature'] },
              { from: 'routes', allow: ['routes', 'feature'] },
              // фичи не импортируют друг друга: общее — в packages/hooks или ui-web
              { from: 'feature', allow: [['feature', { feature: '${from.feature}' }]] },
            ],
          },
        ],
      },
    });
  }
  // Тесты, конфиги и скрипты сборки: литералы и fetch допустимы
  configs.push({
    files: ['**/*.test.{ts,tsx}', '**/scripts/**', '**/*.config.{ts,js,mjs}'],
    languageOptions: { globals: { ...globals.node } },
    rules: { 'no-restricted-globals': 'off' },
  });
  return configs;
}

export default sosed;
