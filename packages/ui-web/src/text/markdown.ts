// Разбор Markdown правовых документов и справки (S48; позже S47, S50, S51) в дерево блоков.
// Подмножество CommonMark + таблицы GFM, которого хватает этим текстам: заголовки, абзацы,
// списки, цитаты, таблицы, черта; внутри строки — **жирный**, *курсив*, `код`, [ссылка](url).
// Сырой HTML не разбирается и выводится текстом: innerHTML нет, XSS неоткуда взяться.
// Вложенных списков нет: строка с отступом продолжает текущий пункт.

export type Inline =
  | { type: 'text'; value: string }
  | { type: 'strong'; children: Inline[] }
  | { type: 'em'; children: Inline[] }
  | { type: 'code'; value: string }
  | { type: 'link'; href: string; children: Inline[] };

export type Block =
  | { type: 'heading'; level: 2 | 3 | 4; children: Inline[] }
  | { type: 'paragraph'; children: Inline[] }
  | { type: 'list'; ordered: boolean; start: number; items: Inline[][] }
  | { type: 'quote'; children: Inline[] }
  | { type: 'table'; head: Inline[][]; rows: Inline[][][] }
  | { type: 'rule' };

const HEADING = /^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const RULE = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const QUOTE = /^\s{0,3}>\s?/;
const BULLET = /^\s{0,3}[-*+]\s+/;
const ORDERED = /^\s{0,3}(\d{1,9})[.)]\s+/;
const TABLE_ROW = /^\s*\|/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const SAFE_HREF = /^(https?:|mailto:|tel:|\/|#)/i;
const ESCAPABLE = /[\\`*_{}[\]()#+\-.!|>~]/;

const isBlank = (line: string) => line.trim() === '';

/** Строка начинает новый блок: абзац или пункт списка на ней заканчивается. */
function startsBlock(line: string): boolean {
  return (
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    BULLET.test(line) ||
    ORDERED.test(line) ||
    TABLE_ROW.test(line)
  );
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  const at = (index: number) => lines[index] ?? '';

  while (i < lines.length) {
    const line = at(i);
    if (isBlank(line)) {
      i += 1;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const level = Math.min(Math.max(heading[1]?.length ?? 2, 2), 4) as 2 | 3 | 4;
      blocks.push({ type: 'heading', level, children: parseInline(heading[2] ?? '') });
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ type: 'rule' });
      i += 1;
      continue;
    }
    if (QUOTE.test(line)) {
      const parts: string[] = [];
      while (i < lines.length && QUOTE.test(at(i))) {
        parts.push(at(i).replace(QUOTE, '').trim());
        i += 1;
      }
      blocks.push({ type: 'quote', children: parseInline(parts.filter(Boolean).join(' ')) });
      continue;
    }
    if (TABLE_ROW.test(line) && TABLE_SEPARATOR.test(at(i + 1))) {
      const head = splitRow(line).map(parseInline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(at(i))) {
        const cells = splitRow(at(i));
        rows.push(head.map((_, c) => parseInline(cells[c] ?? '')));
        i += 1;
      }
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    const ordered = ORDERED.exec(line);
    if (ordered || BULLET.test(line)) {
      const marker = ordered ? ORDERED : BULLET;
      const items: string[] = [];
      while (i < lines.length && marker.test(at(i))) {
        let item = at(i).replace(marker, '').trim();
        i += 1;
        // продолжение пункта: непустая строка, которая не начинает новый блок
        while (i < lines.length && !isBlank(at(i)) && !startsBlock(at(i))) {
          item += ` ${at(i).trim()}`;
          i += 1;
        }
        items.push(item);
        // пустая строка между пунктами одного списка не разрывает его
        if (isBlank(at(i)) && marker.test(at(i + 1))) i += 1;
      }
      blocks.push({
        type: 'list',
        ordered: Boolean(ordered),
        start: ordered ? Number(ordered[1]) : 1,
        items: items.map(parseInline),
      });
      continue;
    }
    const parts = [line.trim()];
    i += 1;
    while (i < lines.length && !isBlank(at(i)) && !startsBlock(at(i))) {
      parts.push(at(i).trim());
      i += 1;
    }
    blocks.push({ type: 'paragraph', children: parseInline(parts.join(' ')) });
  }
  return blocks;
}

function splitRow(line: string): string[] {
  const cells: string[] = [];
  let current = '';
  const body = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (ch === '\\' && body[i + 1] === '|') {
      current += '|';
      i += 1;
    } else if (ch === '|') {
      cells.push(current.trim());
      current = '';
    } else {
      current += ch;
    }
  }
  cells.push(current.trim());
  return cells;
}

export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  let text = '';
  const flush = () => {
    if (text) out.push({ type: 'text', value: text });
    text = '';
  };
  let i = 0;
  while (i < source.length) {
    const ch = source.charAt(i);
    const next = source.charAt(i + 1);
    if (ch === '\\' && ESCAPABLE.test(next)) {
      text += next;
      i += 2;
      continue;
    }
    if (ch === '`') {
      const end = source.indexOf('`', i + 1);
      if (end > i + 1) {
        flush();
        out.push({ type: 'code', value: source.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    if (ch === '*' && next === '*') {
      const end = source.indexOf('**', i + 2);
      if (end > i + 2) {
        flush();
        out.push({ type: 'strong', children: parseInline(source.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }
    if (ch === '*' && next !== ' ' && next !== '') {
      const end = closingStar(source, i + 1);
      if (end > i + 1) {
        flush();
        out.push({ type: 'em', children: parseInline(source.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    if (ch === '[') {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)/.exec(source.slice(i));
      if (link) {
        flush();
        const [whole, label = '', href = ''] = link;
        const children = parseInline(label);
        if (SAFE_HREF.test(href)) out.push({ type: 'link', href, children });
        else out.push(...children);
        i += whole.length;
        continue;
      }
    }
    text += ch;
    i += 1;
  }
  flush();
  return out;
}

/** Закрывающая одиночная `*` курсива: не часть `**` и не после пробела. */
function closingStar(source: string, from: number): number {
  for (let i = from; i < source.length; i += 1) {
    if (source.charAt(i) !== '*') continue;
    if (source.charAt(i + 1) === '*') {
      i += 1;
      continue;
    }
    if (source.charAt(i - 1) !== ' ') return i;
  }
  return -1;
}

/** Текст без разметки: для заголовков вкладок, aria-label и поиска. */
export function inlineText(nodes: Inline[]): string {
  return nodes
    .map((node) =>
      node.type === 'text' || node.type === 'code' ? node.value : inlineText(node.children),
    )
    .join('');
}
