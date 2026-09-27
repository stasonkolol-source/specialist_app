// Рендер и доступность примитивов 0.19a. Тексты в тестах — данные, а не интерфейс.
import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

import { OUT_PATH, SPEC_PATH, renderIcons } from '../scripts/icons.ts';
import { Avatar, initials, paletteFor } from './Avatar.tsx';
import { Badge } from './Badge.tsx';
import { Button, IconButton } from './Button.tsx';
import { Card } from './Card.tsx';
import { ICON_NAMES, Icon } from './icon/Icon.tsx';
import { HStack, Stack } from './layout/Stack.tsx';
import { TabBar } from './TabBar.tsx';
import { a11yViolations } from './testing/a11y.ts';
import { Heading, SectionTitle, Text } from './text/Heading.tsx';

describe('Icon', () => {
  it('иконки SPEC §3 — актуальны (pnpm -F ui-web icons)', () => {
    expect(readFileSync(OUT_PATH, 'utf8')).toBe(renderIcons(readFileSync(SPEC_PATH, 'utf8')));
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(60);
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
    expect(screen.getByRole('button', { name: 'Изменить' }).className).toContain('h-9');
    expect(screen.getByRole('button', { name: 'Отменить' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('link', { name: 'Профиль' }).className).toContain('w-full');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('IconButton — подпись обязательна, активное состояние', async () => {
    const { container } = render(<IconButton icon="heart" label="В избранное" active />);
    const button = screen.getByRole('button', { name: 'В избранное' });
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.className).toContain('text-danger');
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
      </>,
    );
    expect(screen.getByText('Срочно').className).toContain('bg-urgent-soft');
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
        plus={{ label: 'Создать заявку', href: '/create' }}
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
    expect(onNavigate).toHaveBeenCalledWith('/create', expect.anything());
    expect(await a11yViolations(container)).toEqual([]);
  });
});
