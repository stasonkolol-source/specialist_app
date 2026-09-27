// Разбор и отрисовка Markdown правовых документов (S48). Тексты — данные фикстур.
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { a11yViolations } from '../testing/a11y.ts';
import { Markdown } from './Markdown.tsx';
import { inlineText, parseInline, parseMarkdown } from './markdown.ts';

const DOCUMENT = `Вступление в две
строки.

## 1. Кто может пользоваться

- Только взрослые, **18 лет** и старше.
- Один человек — один аккаунт,
  продолжение пункта.

- Пункт после пустой строки.

1. **Правила и фильтры.** Слова.
2. Вторая проверка.

> Цитата
> в две строки.

| Код | Нарушение |
|---|---|
| \`spam_ad\` | Спам \\| реклама |
| \`other\` |

---

### Подраздел

Текст *курсивом* и [ссылка](https://example.test) и [опасная](javascript:alert(1)).
<script>alert(1)</script>`;

describe('parseMarkdown', () => {
  it('разбирает блоки документа', () => {
    const blocks = parseMarkdown(DOCUMENT);
    expect(blocks.map((b) => b.type)).toEqual([
      'paragraph',
      'heading',
      'list',
      'list',
      'quote',
      'table',
      'rule',
      'heading',
      'paragraph',
    ]);
    const [intro, heading, bullets, ordered, quote, table] = blocks;
    expect(intro).toEqual({
      type: 'paragraph',
      children: [{ type: 'text', value: 'Вступление в две строки.' }],
    });
    expect(heading).toMatchObject({ type: 'heading', level: 2 });
    expect(bullets?.type === 'list' && bullets.items.map(inlineText)).toEqual([
      'Только взрослые, 18 лет и старше.',
      'Один человек — один аккаунт, продолжение пункта.',
      'Пункт после пустой строки.',
    ]);
    expect(ordered).toMatchObject({ type: 'list', ordered: true, start: 1 });
    expect(quote?.type === 'quote' && inlineText(quote.children)).toBe('Цитата в две строки.');
    expect(table?.type === 'table' && table.rows.map((row) => row.map(inlineText))).toEqual([
      ['spam_ad', 'Спам | реклама'],
      ['other', ''],
    ]);
  });

  it('разбирает строку: жирный, курсив, код, ссылки и экранирование', () => {
    expect(parseInline('a **b *c* b** `d` \\*e\\* [f](/legal/terms)')).toEqual([
      { type: 'text', value: 'a ' },
      {
        type: 'strong',
        children: [
          { type: 'text', value: 'b ' },
          { type: 'em', children: [{ type: 'text', value: 'c' }] },
          { type: 'text', value: ' b' },
        ],
      },
      { type: 'text', value: ' ' },
      { type: 'code', value: 'd' },
      { type: 'text', value: ' *e* ' },
      { type: 'link', href: '/legal/terms', children: [{ type: 'text', value: 'f' }] },
    ]);
    expect(parseInline('2 * 3 = 6, 18+')).toEqual([{ type: 'text', value: '2 * 3 = 6, 18+' }]);
  });

  it('не делает ссылку из небезопасного адреса', () => {
    expect(parseInline('[x](javascript:alert(1))')).toEqual([
      { type: 'text', value: 'x' },
      { type: 'text', value: ')' },
    ]);
  });
});

describe('Markdown', () => {
  it('рисует элементы без HTML из текста и проходит axe', async () => {
    const { container } = render(<Markdown source={DOCUMENT} lang="ru" />);
    expect(
      screen.getByRole('heading', { level: 2, name: '1. Кто может пользоваться' }),
    ).toBeTruthy();
    expect(screen.getByRole('heading', { level: 3, name: 'Подраздел' })).toBeTruthy();
    expect(screen.getAllByRole('list')).toHaveLength(2);
    const table = screen.getByRole('table');
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(['Код', 'Нарушение']);
    const link = screen.getByRole('link', { name: 'ссылка' });
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.queryByRole('link', { name: 'опасная' })).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.firstElementChild?.getAttribute('lang')).toBe('ru');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('широкую таблицу рисует списком записей: слова не рвутся посередине', async () => {
    const source = [
      '| Сервис | Для чего | Где |',
      '|---|---|---|',
      '| Hetzner | Серверы | Германия (ЕС) |',
      '| OpenAI | Проверка текстов | США |',
    ].join('\n');
    const { container } = render(<Markdown source={source} />);
    expect(screen.queryByRole('table')).toBeNull();
    const records = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(records.map((li) => li.textContent)).toEqual([
      'HetznerДля чего: СерверыГде: Германия (ЕС)',
      'OpenAIДля чего: Проверка текстовГде: США',
    ]);
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('сдвигает уровни заголовков внутри секции', () => {
    render(<Markdown source={'## Раздел\n\n### Пункт'} headingLevel={3} />);
    expect(screen.getByRole('heading', { level: 3, name: 'Раздел' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 4, name: 'Пункт' })).toBeTruthy();
  });
});
