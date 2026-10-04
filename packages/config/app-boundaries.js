// Правило границ Mini App (ADR-0020 §13): app собирает routes и фичи, routes — фичи, фича — только
// себя. Раньше это делал eslint-plugin-boundaries, но он тянет micromatch → braces с уязвимостью
// GHSA-vfj7-8cjw-p6xm без исправленной версии (pnpm audit красный). Политика в три строки, поэтому
// своё правило: импорт относим к элементу по пути, без резолвера и глобов.
import path from 'node:path';

// Элемент — по пути файла от корня пакета, как шаблоны плагина src/app/**, src/routes/**,
// src/features/*/** (имя фичи — первый каталог под features). Остальное (src/main.tsx, src/testing/**,
// файлы прямо в src/features) — не элемент: не проверяется ни как источник, ни как цель импорта.
const ELEMENT = /^src\/(?:(app|routes)|features\/([^/]+))\/./;

// Что элементу можно импортировать; фиче — только саму себя (имя сверяется отдельно)
const ALLOWED = {
  app: ['app', 'routes', 'feature'],
  routes: ['routes', 'feature'],
  feature: ['feature'],
};

function elementOf(root, file) {
  const match = ELEMENT.exec(path.relative(root, file).split(path.sep).join('/'));
  if (!match) return null;
  return match[1] ? { type: match[1] } : { type: 'feature', name: match[2] };
}

export const appBoundaries = {
  meta: {
    type: 'problem',
    docs: { description: 'Границы Mini App: app → routes → фичи, фичи не импортируют друг друга' },
    messages: {
      otherFeature: 'Фича {{from}} не импортирует фичу {{to}}: общее — в packages/hooks или ui-web',
      feature: 'Фича {{from}} не импортирует {{to}}',
      layer: '{{from}} не импортируют {{to}}',
    },
    schema: [
      { type: 'object', properties: { root: { type: 'string' } }, additionalProperties: false },
    ],
  },
  create(context) {
    // корень пакета — sosed({ root }) (import.meta.dirname пакета), иначе каталог запуска ESLint
    const root = context.options[0]?.root ?? context.cwd;
    const file = context.filename;
    const from = path.isAbsolute(file) ? elementOf(root, file) : null;
    if (!from) return {};

    const check = (source) => {
      // только относительные пути: пакеты (@sosed/*) — не элементы, алиасов в apps/tma нет
      const spec = source?.type === 'Literal' ? source.value : null;
      if (typeof spec !== 'string' || !/^\.{1,2}\//.test(spec)) return;
      const to = elementOf(root, path.resolve(path.dirname(file), spec));
      if (!to) return;
      const allowed =
        ALLOWED[from.type].includes(to.type) && (from.type !== 'feature' || from.name === to.name);
      if (allowed) return;
      // нарушить может только routes (→ app) или фича (→ app, routes, чужая фича)
      const messageId =
        from.type !== 'feature' ? 'layer' : to.type === 'feature' ? 'otherFeature' : 'feature';
      const data = { from: from.name ?? from.type, to: to.name ?? to.type };
      context.report({ node: source, messageId, data });
    };
    // import и import type, export … from, export * from и import('…') — у всех путь в source
    return {
      ImportDeclaration: (node) => check(node.source),
      ExportNamedDeclaration: (node) => check(node.source),
      ExportAllDeclaration: (node) => check(node.source),
      ImportExpression: (node) => check(node.source),
    };
  },
};
