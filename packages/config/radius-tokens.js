// Радиусы в классах — только токены design-tokens (rounded-card, rounded-field…). theme.generated.css
// сбрасывает шкалу Tailwind (--radius-*: initial), поэтому rounded-xl, rounded-md и удалённые токены
// не дают CSS вовсе: угол молча становится прямым — так на S30 были квадратными заметки чата и плашка
// скрытого контакта. Tailwind о неизвестном классе не предупреждает, поэтому — правило.

// rounded, rounded-t, rounded-tl… и значение после них (токен, none, full, [6px], (--var))
const RADIUS = /^rounded(?:-(?:s|e|t|r|b|l|ss|se|ee|es|tl|tr|br|bl))?(?:-(.+))?$/;
// Без темы Tailwind даёт только эти значения
const STATIC = ['none', 'full'];

/** Утилита без вариантов (`md:`, `hover:`, `[&_a]:`) и без «!». */
function utilityOf(cls) {
  let depth = 0;
  let start = 0;
  for (let i = 0; i < cls.length; i += 1) {
    const c = cls[i];
    if (c === '[' || c === '(') depth += 1;
    else if (c === ']' || c === ')') depth -= 1;
    else if (c === ':' && depth === 0) start = i + 1;
  }
  return cls.slice(start).replace(/^!|!$/g, '');
}

export const radiusTokens = {
  meta: {
    type: 'problem',
    docs: { description: 'Радиусы — только токены design-tokens: шкала Tailwind сброшена' },
    messages: {
      unknown:
        '«{{cls}}» не даёт CSS — шкала Tailwind сброшена. Радиус — токен ({{tokens}}), none, full или [значение]',
    },
    schema: [
      {
        type: 'object',
        properties: { tokens: { type: 'array', items: { type: 'string' } } },
        additionalProperties: false,
      },
    ],
  },
  create(context) {
    const tokens = context.options[0]?.tokens ?? [];
    const allowed = new Set([...tokens, ...STATIC]);
    const check = (node, text) => {
      for (const cls of text.split(/\s+/)) {
        const match = RADIUS.exec(utilityOf(cls));
        if (!match) continue;
        const value = match[1];
        if (value && (allowed.has(value) || /^[[(]/.test(value))) continue;
        context.report({ node, messageId: 'unknown', data: { cls, tokens: tokens.join(', ') } });
      }
    };
    // классы бывают в любой строке: className, cx(…), словари вариантов (TONE, SKELETON_RADIUS)
    return {
      Literal(node) {
        if (typeof node.value === 'string') check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.cooked ?? node.value.raw);
      },
    };
  },
};
