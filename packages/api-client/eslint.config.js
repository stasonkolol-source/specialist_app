import { sosed } from '@sosed/config/eslint';

// src/generated — вывод orval: правится только перегенерацией (make openapi)
export default [
  { ignores: ['src/generated/**'] },
  ...sosed({ root: import.meta.dirname, react: true, allowFetchIn: ['src/mutator.ts'] }),
];
