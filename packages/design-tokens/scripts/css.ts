// Простой разбор плоского CSS (без вложенных блоков) для сверки с design/ui.css.

export type Declarations = Record<string, string>;

/** Селектор → объявления; одинаковые селекторы сливаются, как в каскаде. */
export function parseRules(css: string): Map<string, Declarations> {
  const rules = new Map<string, Declarations>();
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const [, selectors = '', body = ''] of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const decls: Declarations = {};
    for (const decl of body.split(';')) {
      const i = decl.indexOf(':');
      if (i > 0) decls[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
    for (const selector of selectors.split(',')) {
      const key = selector.trim();
      rules.set(key, { ...rules.get(key), ...decls });
    }
  }
  return rules;
}

/** Только пользовательские свойства (`--x`) правила, без префикса `--`. */
export function customProperties(decls: Declarations | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(decls ?? {})
      .filter(([k]) => k.startsWith('--'))
      .map(([k, v]) => [k.slice(2), v]),
  );
}

/** Значение для сравнения: #fff → #ffffff, регистр и пробелы не важны. */
export function normalizeValue(value: string): string {
  const v = value.trim().toLowerCase().replace(/\s+/g, ' ');
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(v);
  return short ? `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}` : v;
}
