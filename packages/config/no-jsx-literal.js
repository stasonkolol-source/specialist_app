// Правило «тексты только через t()» (ADR-0020 §13). eslint-plugin-i18next 6.1.5 под ESLint 10 не находит
// текст в JSX (проверено тестом), поэтому своё правило: текст-ребёнок JSX и текстовые атрибуты с буквами.
const LETTER = /\p{L}/u;
const TEXT_ATTRIBUTES = new Set(['aria-label', 'title', 'alt', 'placeholder', 'label']);

function hasLetters(value) {
  return typeof value === 'string' && LETTER.test(value);
}

/** Внутри <Trans> текст — это ключ разметки, его не трогаем. */
function insideTrans(node) {
  for (let p = node.parent; p; p = p.parent) {
    if (p.type === 'JSXElement' && p.openingElement.name.name === 'Trans') return true;
  }
  return false;
}

export const noJsxLiteral = {
  meta: {
    type: 'problem',
    docs: { description: 'Литералы в JSX запрещены: тексты — только через t()' },
    messages: { literal: 'Текст в JSX — только через t(): «{{text}}»' },
    schema: [],
  },
  create(context) {
    const report = (node, text) =>
      context.report({ node, messageId: 'literal', data: { text: text.trim().slice(0, 40) } });
    return {
      JSXText(node) {
        if (hasLetters(node.value) && !insideTrans(node)) report(node, node.value);
      },
      JSXAttribute(node) {
        const name = typeof node.name.name === 'string' ? node.name.name : '';
        const value = node.value;
        if (!TEXT_ATTRIBUTES.has(name) || !value) return;
        if (value.type === 'Literal' && hasLetters(value.value)) report(value, value.value);
      },
      'JSXExpressionContainer > Literal'(node) {
        if (node.parent.parent?.type === 'JSXAttribute') return;
        if (hasLetters(node.value)) report(node, node.value);
      },
      'JSXExpressionContainer > TemplateLiteral'(node) {
        if (node.parent.parent?.type === 'JSXAttribute' || node.expressions.length > 0) return;
        const text = node.quasis.map((q) => q.value.cooked ?? '').join('');
        if (hasLetters(text)) report(node, text);
      },
    };
  },
};
