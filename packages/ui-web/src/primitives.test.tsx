// Рендер и доступность примитивов 0.19a. Тексты в тестах — данные, а не интерфейс.
import { fireEvent, render, screen } from '@testing-library/react';
import type { MouseEvent } from 'react';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

import { OUT_PATH, SPEC_PATH, renderIcons } from '../scripts/icons.ts';
import { Avatar, initials, paletteFor } from './Avatar.tsx';
import { Badge } from './Badge.tsx';
import { Button, IconButton } from './Button.tsx';
import { Card } from './Card.tsx';
import { colourOr } from './cx.ts';
import { color } from '@sosed/design-tokens';
import tokens from '@sosed/design-tokens/tokens.json' with { type: 'json' };

import { ICON_NAMES, ICON_STROKE, Icon } from './icon/Icon.tsx';
import { HStack, Stack } from './layout/Stack.tsx';
import { TabBar } from './TabBar.tsx';
import { a11yViolations } from './testing/a11y.ts';
import { Heading, SectionTitle, Text } from './text/Heading.tsx';

describe('Icon', () => {
  it('иконки SPEC §3 — актуальны (pnpm -F ui-web icons)', () => {
    expect(readFileSync(OUT_PATH, 'utf8')).toBe(renderIcons(readFileSync(SPEC_PATH, 'utf8')));
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(60);
  });

  // UXM-6: «Бьюти» (sparkles) рисовалась запасной grid, как «Все услуги» рядом
  it('у каждой иконки каталога (seed taxonomy) есть рисунок', () => {
    const seed = readFileSync(
      `${import.meta.dirname}/../../../backend/seeds/catalog/taxonomy.yaml`,
      'utf8',
    );
    const names = [...seed.matchAll(/^\s*icon: ([a-z0-9-]+)\s*$/gm)].map(([, name]) => name);
    expect(names.length).toBeGreaterThan(10);
    expect(names.filter((name) => !(ICON_NAMES as readonly string[]).includes(name ?? ''))).toEqual(
      [],
    );
  });

  it('штрих по размеру — как в токенах: на экране линии одной толщины', () => {
    expect(ICON_STROKE).toEqual(tokens.icon.strokes);
    const { container } = render(
      <>
        <Icon name="check" size={16} />
        <Icon name="search" size={32} />
      </>,
    );
    const [small, large] = container.querySelectorAll('svg');
    expect(small?.getAttribute('stroke-width')).toBe('2.2');
    expect(large?.getAttribute('stroke-width')).toBe('1.4');
  });

  it('декоративная — aria-hidden, штрих 1.8; с подписью — role=img', async () => {
    const { container } = render(
      <>
        <Icon name="home" />
        <Icon name="star" size={16} label="Рейтинг" />
      </>,
    );
    const [decorative, labeled] = container.querySelectorAll('svg');
    expect(decorative?.getAttribute('aria-hidden')).toBe('true');
    expect(decorative?.getAttribute('stroke-width')).toBe('1.8');
    expect(labeled?.getAttribute('class')).toContain('fill-current');
    expect(screen.getByRole('img', { name: 'Рейтинг' })).toBeTruthy();
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Stack и HStack', () => {
  it('отступы по шкале ui.css', () => {
    const { container } = render(
      <Stack gap={24}>
        <HStack between>
          <span>a</span>
          <span>b</span>
        </HStack>
      </Stack>,
    );
    expect(container.firstElementChild?.className).toContain('gap-6');
    expect(container.querySelector('.justify-between')?.className).toContain('gap-3');
  });
});

describe('Heading, SectionTitle, Text', () => {
  it('уровни заголовков и доступность', async () => {
    const { container } = render(
      <>
        <Heading variant="h1">Мастера рядом</Heading>
        <SectionTitle>Категории</SectionTitle>
        <Heading variant="h3">Детали</Heading>
        <Text variant="cap">15 мин назад</Text>
      </>,
    );
    expect(screen.getByRole('heading', { level: 1 }).className).toContain('font-display');
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(2);
    expect(await a11yViolations(container)).toEqual([]);
  });

  // SMOKE-8: при двух цветах побеждал поздний в CSS (.text-text2), ошибка оставалась серой
  it('свой цвет вызывающего заменяет серый подписи, а не спорит с ним', () => {
    render(
      <>
        <Text variant="cap" className="text-danger">
          Выберите категорию
        </Text>
        <Text variant="cap">Подсказка</Text>
        <Text secondary className="text-accent">
          Ссылка
        </Text>
        <Text variant="cap" className="hover:text-accent">
          Наведение
        </Text>
        <SectionTitle className="text-danger">Ошибки</SectionTitle>
      </>,
    );
    const classes = (text: string) => screen.getByText(text).className.split(' ');
    expect(classes('Выберите категорию')).toContain('text-danger');
    expect(classes('Выберите категорию')).not.toContain('text-text2');
    expect(classes('Подсказка')).toContain('text-text2');
    expect(classes('Ссылка')).not.toContain('text-text2');
    expect(classes('Наведение')).toContain('text-text2');
    expect(classes('Ошибки')).not.toContain('text-text2');
  });

  it('цвет — любой токен темы, размер шрифта цветом не считается', () => {
    for (const name of Object.keys(color.light)) {
      expect(colourOr('text-text2', `font-semibold text-${name}`)).toBe(false);
    }
    for (const size of ['text-cap', 'text-sm', 'text-body', 'text-title', 'text-section']) {
      expect(colourOr('text-text2', size)).toBe('text-text2');
    }
    expect(colourOr('text-text2', undefined)).toBe('text-text2');
  });
});

describe('Card', () => {
  it('div, ссылка и кнопка', async () => {
    const onClick = vi.fn();
    const { container } = render(
      <>
        <Card>Текст</Card>
        <Card href="/j/1">Заявка</Card>
        <Card onClick={onClick} tight>
          Отклик
        </Card>
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отклик' }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.getByRole('link', { name: 'Заявка' }).getAttribute('href')).toBe('/j/1');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('ссылка с переходом внутри приложения', () => {
    const navigate = vi.fn((event: MouseEvent<HTMLElement>) => event.preventDefault());
    render(
      <Card href="/become/about" onClick={navigate}>
        Кабинет специалиста
      </Card>,
    );
    fireEvent.click(screen.getByRole('link', { name: 'Кабинет специалиста' }));
    expect(navigate).toHaveBeenCalledOnce();
  });
});

describe('Button и IconButton', () => {
  it('варианты, размер, иконка, disabled', async () => {
    const { container } = render(
      <>
        <Button>Откликнуться</Button>
        <Button variant="secondary" icon="chat">
          Написать
        </Button>
        <Button variant="outline" size="sm">
          Изменить
        </Button>
        <Button variant="danger" disabled>
          Отменить
        </Button>
        <Button href="/s/1" full>
          Профиль
        </Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Откликнуться' }).className).toContain('bg-accent');
    const outline = screen.getByRole('button', { name: 'Изменить' }).className.split(' ');
    expect(outline).toContain('h-9');
    // рамка .btn.out: border-0 в CSS идёт после border и снял бы её
    expect(outline).toContain('border');
    expect(outline).not.toContain('border-0');
    expect(screen.getByRole('button', { name: 'Отменить' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('link', { name: 'Профиль' }).className).toContain('w-full');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('IconButton — подпись обязательна, активное состояние', async () => {
    const { container } = render(
      <>
        <IconButton icon="heart" label="В избранное" active />
        <IconButton icon="heart" label="Сохранить" />
      </>,
    );
    const button = screen.getByRole('button', { name: 'В избранное' });
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.className).toContain('text-danger');
    // состояние не только цветом: сердце залито, у выключенной кнопки — контур
    expect(button.querySelector('svg')?.getAttribute('class')).toContain('fill-current');
    const off = screen.getByRole('button', { name: 'Сохранить' });
    expect(off.querySelector('svg')?.getAttribute('class')).toContain('fill-none');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('IconButton с href — ссылка на экран (шестерёнка S42 → S43), переход — onClick', async () => {
    const onClick = vi.fn((event: MouseEvent<HTMLElement>) => event.preventDefault());
    const { container } = render(
      <IconButton
        icon="settings"
        label="Настройки уведомлений"
        href="/settings"
        onClick={onClick}
      />,
    );
    const link = screen.getByRole('link', { name: 'Настройки уведомлений' });
    expect(link.getAttribute('href')).toBe('/settings');
    fireEvent.click(link);
    expect(onClick).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Badge', () => {
  it('тона ui.css', async () => {
    const { container } = render(
      <>
        <Badge tone="ok" icon="check">
          Телефон подтверждён
        </Badge>
        <Badge tone="urgent">Срочно</Badge>
        <Badge tone="pro">Pro</Badge>
        <Badge tone="info" dot>
          Приём откликов
        </Badge>
      </>,
    );
    expect(screen.getByText('Срочно').className).toContain('bg-urgent-soft');
    // точка — цветом текста бейджа: в синем бейдже не зелёная
    const dot = screen.getByText('Приём откликов').querySelector('[aria-hidden="true"]');
    expect(dot?.className).toContain('bg-current');
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Avatar', () => {
  it('инициалы, стабильный цвет, подпись', async () => {
    expect(initials('Алексей Морозов')).toBe('АМ');
    expect(initials('  елена  ')).toBe('Е');
    expect(paletteFor('Алексей Морозов')).toBe(paletteFor('Алексей Морозов'));
    const { container } = render(
      <>
        <Avatar name="Алексей Морозов" palette={1} />
        <Avatar name="Мария Ковалёва" size="xl" />
        <Avatar name="Ольга Власова" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" size="sm" />
      </>,
    );
    expect(screen.getByRole('img', { name: 'Алексей Морозов' }).className).toContain('bg-av1');
    expect(screen.getByRole('img', { name: 'Мария Ковалёва' }).className).toContain('size-26');
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('TabBar', () => {
  const items = [
    { id: 'home', label: 'Главная', icon: 'home', href: '/' },
    { id: 'jobs', label: 'Заявки', icon: 'jobs', href: '/jobs', count: 3, countLabel: '3 новых' },
    { id: 'chats', label: 'Сообщения', icon: 'chat', href: '/chats', count: 2 },
    { id: 'me', label: 'Профиль', icon: 'user', href: '/me' },
  ] as const;

  it('пять ячеек с «+» по центру, активная вкладка и счётчики', async () => {
    const onNavigate = vi.fn((_: string, e: { preventDefault: () => void }) => e.preventDefault());
    const { container } = render(
      <TabBar
        items={[...items]}
        activeId="jobs"
        plus={{ id: 'create', label: 'Создать заявку', href: '#/create' }}
        label="Разделы"
        onNavigate={onNavigate}
        position="static"
      />,
    );
    const links = screen.getAllByRole('link');
    expect(links.map((l) => l.getAttribute('aria-label') ?? l.textContent)).toEqual([
      'Главная',
      'Заявки3',
      'Создать заявку',
      'Сообщения2',
      'Профиль',
    ]);
    expect(screen.getByRole('link', { name: /Заявки/ }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('link', { name: 'Создать заявку' }));
    expect(onNavigate).toHaveBeenCalledWith('create', expect.anything());
    fireEvent.click(screen.getByRole('link', { name: 'Профиль' }));
    expect(onNavigate).toHaveBeenLastCalledWith('me', expect.anything());
    expect(await a11yViolations(container)).toEqual([]);
  });
});
