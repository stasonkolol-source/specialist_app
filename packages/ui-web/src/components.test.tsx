// Рендер, поведение и доступность компонентов 0.19b. Тексты — данные фикстур.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { AvatarStack, Chip, Chips, Price } from './Chips.tsx';
import {
  ChatSkeleton,
  FieldSkeleton,
  JobCardSkeleton,
  SpecialistCardSkeleton,
} from './CardSkeletons.tsx';
import { Banner, EmptyState, ProgressBar, Skeleton, Stars, Steps, Toast } from './Feedback.tsx';
import {
  CheckButton,
  Checkbox,
  Option,
  RadioGroup,
  RadioRow,
  Segmented,
  Switch,
} from './form/Choice.tsx';
import { Field, Input, SearchField, Textarea } from './form/Field.tsx';
import { Badge } from './Badge.tsx';
import { Button, LinkButton } from './Button.tsx';
import { FeedRow, Group, Row, RowIcon, Tile, Tiles, UnreadDot } from './Group.tsx';
import { Photo } from './Photo.tsx';
import { ChipSkeleton, RowsSkeleton, TileSkeleton } from './Skeletons.tsx';
import { a11yViolations } from './testing/a11y.ts';

describe('Group и Row', () => {
  it('строки-ссылки, кнопки и статичные; последняя без разделителя', async () => {
    const onClick = vi.fn();
    const { container } = render(
      <Group>
        <Row icon="bell" title="Уведомления" onClick={onClick} />
        <Row title="Язык" subtitle="Русский" chevron href="#lang" />
        <Row title="Версия" trailing={<span>1.0</span>} />
      </Group>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Уведомления' }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.getByRole('link', { name: /Язык/ }).getAttribute('href')).toBe('#lang');
    expect(container.querySelectorAll('.last\\:border-b-0')).toHaveLength(3);
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('FeedRow, UnreadDot, LinkButton (S42)', () => {
  it('строка ленты: ссылка с временем и отметкой, статичная — без ссылки', async () => {
    const onClick = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    const { container } = render(
      <>
        <LinkButton onClick={onClick}>Прочитать все</LinkButton>
        <Group>
          <FeedRow
            title="Новое сообщение"
            leading={<RowIcon icon="chat" palette={2} />}
            meta={
              <>
                <UnreadDot label="Не прочитано" />5 мин
              </>
            }
            href="#chat"
            onClick={onClick}
          >
            Алексей Морозов: «Буду в 19:00»
          </FeedRow>
          <FeedRow
            title="Жалоба рассмотрена"
            leading={<RowIcon icon="flag" neutral />}
            meta="12:05"
          >
            Спасибо! Модераторы проверили профиль
          </FeedRow>
        </Group>
      </>,
    );
    fireEvent.click(screen.getByRole('link', { name: /Новое сообщение/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Прочитать все' }));
    expect(onClick).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('img', { name: 'Не прочитано' })).toBeTruthy();
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(container.querySelector('.bg-bg2.text-text2')).toBeTruthy();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('LinkButton danger — разрушающее действие текстом цвета ошибки (S17)', () => {
    render(<LinkButton danger>Отозвать отклик</LinkButton>);
    const classes = screen.getByRole('button', { name: 'Отозвать отклик' }).className.split(' ');
    expect(classes).toContain('text-danger');
    expect(classes).not.toContain('text-accent');
  });
});

describe('Tiles и Tile', () => {
  it('сетка три колонки, плитка — ссылка с иконкой палитры', async () => {
    const { container } = render(
      <Tiles>
        <Tile icon="wrench" palette={1} label="Мастер на час" href="#c1" />
        <Tile icon="grid" label="Все категории" onClick={() => {}} />
      </Tiles>,
    );
    expect(container.firstElementChild?.className).toContain('grid-cols-3');
    expect(container.querySelector('.bg-av1')).toBeTruthy();
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Chips, AvatarStack, Price', () => {
  it('фильтр-переключатель и счётчик', async () => {
    const onClick = vi.fn();
    const { container } = render(
      <>
        <Chips label="Фильтры" wrap>
          <Chip selected>Сегодня</Chip>
          <Chip accent count={3} onClick={onClick}>
            Подработка
          </Chip>
        </Chips>
        <AvatarStack
          label="3 отклика"
          people={[{ name: 'А Б' }, { name: 'В Г' }, { name: 'Д Е' }]}
        />
        <Price large>5 000 RSD</Price>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Сегодня' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: /Подработка/ }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(
      screen.getByRole('group', { name: '3 отклика' }).querySelectorAll('.-ml-2'),
    ).toHaveLength(2);
    expect(screen.getByText('5 000 RSD').className).toContain('text-price-lg');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('недоступный вариант не нажимается', () => {
    const onClick = vi.fn();
    render(
      <Chip disabled onClick={onClick}>
        до 18:00
      </Chip>,
    );
    const chip = screen.getByRole('button', { name: 'до 18:00' });
    fireEvent.click(chip);
    expect([chip.hasAttribute('disabled'), onClick.mock.calls.length]).toEqual([true, 0]);
  });

  it('чип-раскрывашка сообщает, раскрыт ли список', () => {
    const { rerender } = render(<Chip expanded={false}>Ещё 4 района</Chip>);
    const chip = screen.getByRole('button', { name: 'Ещё 4 района' });
    expect([chip.getAttribute('aria-expanded'), chip.hasAttribute('aria-pressed')]).toEqual([
      'false',
      false,
    ]);

    rerender(<Chip expanded>Свернуть</Chip>);
    expect(screen.getByRole('button', { name: 'Свернуть' }).getAttribute('aria-expanded')).toBe(
      'true',
    );
  });
});

describe('Photo', () => {
  it('плейсхолдер, видео и фото с alt', async () => {
    const { container } = render(
      <>
        <Photo alt="Фото работы" className="size-28" />
        <Photo alt="Видео" video className="size-28" />
        <Photo alt="Кухня" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" className="size-28" />
      </>,
    );
    expect(screen.getByRole('img', { name: 'Фото работы' }).className).toContain('ph-stripes');
    expect(screen.getByRole('img', { name: 'Кухня' }).tagName).toBe('IMG');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('в просмотрщике — фото целиком, без скругления', () => {
    render(
      <Photo
        alt="Люстра"
        fit="contain"
        variants={[{ url: 'https://cdn.test/lg.webp', width: 1600 }]}
        className="w-full"
      />,
    );
    const image = screen.getByRole('img', { name: 'Люстра' });
    expect(image.className).toContain('object-contain');
    expect(image.parentElement?.className).not.toContain('rounded-photo');
  });

  it('без подписи — декоративное: плейсхолдер скрыт от скринридера', async () => {
    const { container } = render(
      <button type="button" aria-label="Работа 2 из 18">
        <Photo alt="" className="size-14" />
      </button>,
    );
    expect(screen.queryByRole('img')).toBeNull();
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Field, Input, Textarea, SearchField', () => {
  it('подпись связана с полем, ошибка и подсказка — через aria-describedby', async () => {
    const { container } = render(
      <>
        <Field label="Бюджет" hint="Можно изменить позже">
          <Input suffix="RSD" defaultValue="5 000" />
        </Field>
        <Field label="Что нужно сделать" error="Заполните поле">
          <Textarea />
        </Field>
        <SearchField label="Поиск" placeholder="Электрик…" />
      </>,
    );
    const budget = screen.getByLabelText('Бюджет');
    expect(budget.getAttribute('aria-describedby')).toBeTruthy();
    // подсказка серая, как .hint: не спорит с введённым текстом и подписью поля
    expect(screen.getByText('Можно изменить позже').className).toContain('text-text2');
    expect(screen.getByText('RSD')).toBeTruthy();
    const description = screen.getByLabelText('Что нужно сделать');
    expect(description.getAttribute('aria-invalid')).toBe('true');
    expect(description.className).toContain('border-danger');
    expect(screen.getByRole('searchbox', { name: 'Поиск' })).toBeTruthy();
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Segmented, Option, Switch', () => {
  function Demo() {
    const [value, setValue] = useState<'a' | 'b' | 'c'>('a');
    const [on, setOn] = useState(false);
    const [checked, setChecked] = useState(false);
    return (
      <>
        <Segmented
          label="Срочность"
          value={value}
          onChange={setValue}
          options={[
            { value: 'a', label: 'Срочно' },
            { value: 'b', label: 'Сегодня' },
            { value: 'c', label: 'На неделе' },
          ]}
        />
        <Switch checked={on} onChange={setOn} label="Уведомления" />
        <Option
          kind="checkbox"
          title="Только проверенные"
          checked={checked}
          onChange={setChecked}
        />
      </>
    );
  }

  it('сегменты — radiogroup со стрелками; switch и checkbox переключаются', async () => {
    const { container } = render(<Demo />);
    const first = screen.getByRole('radio', { name: 'Срочно' });
    expect(first.getAttribute('aria-checked')).toBe('true');
    // дорожка и выбранный сегмент — свои токены: на экране bg2 дорожка видна
    expect(screen.getByRole('radiogroup', { name: 'Срочность' }).className).toContain(
      'bg-seg-track',
    );
    expect(first.className).toContain('bg-seg-on');
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(screen.getByRole('radio', { name: 'Сегодня' }).getAttribute('aria-checked')).toBe(
      'true',
    );
    fireEvent.keyDown(screen.getByRole('radio', { name: 'Сегодня' }), { key: 'ArrowLeft' });
    fireEvent.keyDown(screen.getByRole('radio', { name: 'Срочно' }), { key: 'ArrowLeft' });
    expect(screen.getByRole('radio', { name: 'На неделе' }).getAttribute('aria-checked')).toBe(
      'true',
    );
    const sw = screen.getByRole('switch', { name: 'Уведомления' });
    fireEvent.click(sw);
    expect(sw.getAttribute('aria-checked')).toBe('true');
    const option = screen.getByRole('checkbox', { name: 'Только проверенные' });
    fireEvent.click(option);
    expect(option.getAttribute('aria-checked')).toBe('true');
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('CheckButton (S43) и Row danger', () => {
  function Table() {
    const [bot, setBot] = useState(true);
    return (
      <Group>
        <Row
          title="Сообщения"
          trailing={
            <CheckButton
              className="w-18"
              checked={bot}
              onChange={setBot}
              label="Сообщения — в боте"
            />
          }
        />
        <Row icon="trash" title="Удалить аккаунт" danger chevron href="/delete" />
      </Group>
    );
  }

  it('отметка без подписи рядом называется для скринридера и переключается', async () => {
    const { container } = render(<Table />);
    const box = screen.getByRole('checkbox', { name: 'Сообщения — в боте' });
    expect(box.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(box);
    expect(box.getAttribute('aria-checked')).toBe('false');
    expect(screen.getByRole('link', { name: 'Удалить аккаунт' }).className).toContain(
      'text-danger',
    );
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('RadioGroup, Option (онбординг S02a–b), Checkbox', () => {
  function Languages() {
    const [value, setValue] = useState('ru');
    const option = (id: string, title: string) => (
      <Option
        key={id}
        control="start"
        title={title}
        checked={value === id}
        onChange={() => setValue(id)}
      />
    );
    return (
      <RadioGroup label="Язык интерфейса">
        {option('ru', 'Русский')}
        {option('sr-Latn', 'Srpski')}
        <Option
          control="start"
          title="English"
          trailing={<Badge>скоро</Badge>}
          checked={false}
          onChange={() => setValue('en')}
          disabled
        />
        {option('sr-Cyrl', 'Српски')}
      </RadioGroup>
    );
  }

  it('стрелки выбирают соседний доступный вариант и пропускают «скоро»', async () => {
    const { container } = render(<Languages />);
    const ru = screen.getByRole('radio', { name: 'Русский' });
    ru.focus();
    fireEvent.keyDown(ru, { key: 'ArrowDown' });
    const latin = screen.getByRole('radio', { name: 'Srpski' });
    expect(latin.getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(latin);

    fireEvent.keyDown(latin, { key: 'ArrowDown' });
    expect(screen.getByRole('radio', { name: 'Српски' }).getAttribute('aria-checked')).toBe('true');
    const english = screen.getByRole('radio', { name: 'English' }) as HTMLButtonElement;
    expect(english.disabled).toBe(true);
    expect(english.getAttribute('aria-describedby')).toBeTruthy();
    expect(
      document.getElementById(english.getAttribute('aria-describedby') ?? '')?.textContent,
    ).toBe('скоро');
    fireEvent.click(english);
    expect(english.getAttribute('aria-checked')).toBe('false');

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'ArrowDown' });
    expect(ru.getAttribute('aria-checked')).toBe('true');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('строки выбора в группе (S52): отметка слева, стрелки — по строкам', async () => {
    function Kinds() {
      const [value, setValue] = useState<string | null>(null);
      return (
        <RadioGroup label="Что случилось?">
          <Group>
            {['Не пришёл', 'Сделал плохо или не то', 'Другое'].map((title) => (
              <RadioRow
                key={title}
                title={title}
                checked={value === title}
                onChange={() => setValue(title)}
              />
            ))}
          </Group>
        </RadioGroup>
      );
    }
    const { container } = render(<Kinds />);
    const first = screen.getByRole('radio', { name: 'Не пришёл' });
    expect(first.getAttribute('aria-checked')).toBe('false');

    fireEvent.click(first);
    first.focus();
    fireEvent.keyDown(first, { key: 'ArrowDown' });

    expect(first.getAttribute('aria-checked')).toBe('false');
    const second = screen.getByRole('radio', { name: 'Сделал плохо или не то' });
    expect(second.getAttribute('aria-checked')).toBe('true');
    expect(second.firstElementChild?.className).toContain('border-7');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('с описанием заголовок варианта жирный (S20b «Срочно»), без описания — обычный', () => {
    render(
      <RadioGroup label="Когда">
        <Option title="Срочно" description="в течение 2 часов" checked onChange={() => {}} />
        <Option title="Русский" checked={false} onChange={() => {}} />
      </RadioGroup>,
    );
    expect(screen.getByText('Срочно').className).toContain('font-semibold');
    expect(screen.getByText('Русский').className).not.toContain('font-semibold');
  });

  it('отметка слева или справа, крупная карточка с плиткой', () => {
    render(
      <RadioGroup label="Цель">
        <Option control="start" title="Нови-Сад" checked onChange={() => undefined} />
        <Option
          large
          leading={<RowIcon icon="search" palette={1} xl />}
          title="Найти мастера"
          description="Электрик, маникюр, уборка"
          checked={false}
          onChange={() => undefined}
        />
      </RadioGroup>,
    );
    const city = screen.getByRole('radio', { name: 'Нови-Сад' });
    expect(city.firstElementChild?.className).toContain('rounded-full');
    const intent = screen.getByRole('radio', {
      name: 'Найти мастера',
      description: 'Электрик, маникюр, уборка',
    });
    expect(intent.className).toContain('items-start');
    expect(intent.lastElementChild?.className).toContain('mt-2.75');
    expect(intent.firstElementChild?.className).toContain('size-11');
  });

  it('галочка: вся строка нажимается, ошибка связана с полем', async () => {
    function Demo() {
      const [checked, setChecked] = useState(false);
      return (
        <>
          <Checkbox checked={checked} onChange={setChecked} invalid={!checked} describedBy="err">
            Мне есть 18 лет, я принимаю правила площадки
          </Checkbox>
          <p id="err">Отметьте галочку</p>
        </>
      );
    }
    const { container } = render(<Demo />);
    const box = screen.getByRole('checkbox', {
      name: 'Мне есть 18 лет, я принимаю правила площадки',
    });
    expect(box.getAttribute('aria-invalid')).toBe('true');
    expect(box.getAttribute('aria-describedby')).toBe('err');
    fireEvent.click(box);
    expect(box.getAttribute('aria-checked')).toBe('true');
    expect(box.getAttribute('aria-invalid')).toBeNull();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('недоступная галочка не нажимается', () => {
    const onChange = vi.fn();
    render(
      <Checkbox checked={false} onChange={onChange} disabled>
        Сохранить как шаблон
      </Checkbox>,
    );
    const box = screen.getByRole('checkbox', { name: 'Сохранить как шаблон' });
    fireEvent.click(box);
    expect(onChange).not.toHaveBeenCalled();
    expect((box as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Steps, ProgressBar, Stars', () => {
  it('прогресс и оценка', async () => {
    const onChange = vi.fn();
    const { container } = render(
      <>
        <Steps total={5} current={2} label="Шаг 2 из 5" />
        <ProgressBar value={150} label="Готово" />
        <Stars value={3} onChange={onChange} label="Оценка" starLabel={(n) => `${n} из 5`} />
        <Stars value={4} label="4 из 5" starLabel={(n) => `${n}`} />
      </>,
    );
    const steps = screen.getByRole('progressbar', { name: 'Шаг 2 из 5' });
    expect(steps.querySelectorAll('.bg-accent')).toHaveLength(2);
    const bar = screen.getByRole('progressbar', { name: 'Готово' })
      .firstElementChild as HTMLElement;
    expect(bar.style.width).toBe('100%');
    fireEvent.click(screen.getByRole('radio', { name: '5 из 5' }));
    expect(onChange).toHaveBeenCalledWith(5);
    expect(screen.getByRole('img', { name: '4 из 5' }).querySelectorAll('.text-star')).toHaveLength(
      4,
    );
    // пустая звезда для показа — цвет рамки поля: «4» и «5» различимы
    expect(
      screen.getByRole('img', { name: '4 из 5' }).querySelectorAll('.text-field'),
    ).toHaveLength(1);
    // при выставлении оценки пустые — контур цвета text2, выбранные — залитые
    const empty = screen.getByRole('radio', { name: '4 из 5' });
    expect(empty.className).toContain('text-text2');
    expect(empty.querySelector('svg')?.getAttribute('class')).toContain('fill-none');
    const chosen = screen.getByRole('radio', { name: '3 из 5' });
    expect(chosen.className).toContain('text-star');
    expect(chosen.querySelector('svg')?.getAttribute('class')).toContain('fill-current');
    expect(await a11yViolations(container)).toEqual([]);
  });
});

describe('Banner, EmptyState, Toast, Skeleton', () => {
  it('тона баннера, пустое состояние, тост со статусом, скелетон скрыт', async () => {
    const { container } = render(
      <>
        <Banner tone="warn">
          Не вносите предоплату. <a href="#more">Подробнее</a>
        </Banner>
        <Banner tone="danger" role="alert">
          Ошибка
        </Banner>
        <EmptyState icon="jobs" title="Пока нет заявок">
          Опубликуйте заявку
        </EmptyState>
        <Toast position="static">Сохранено</Toast>
        <Skeleton round className="size-12" />
      </>,
    );
    expect(screen.getByText(/Не вносите/).closest('div')?.parentElement?.className).toContain(
      'bg-urgent-soft',
    );
    expect(screen.getByRole('alert').textContent).toBe('Ошибка');
    expect(screen.getByRole('heading', { name: 'Пока нет заявок' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('Сохранено');
    expect(container.querySelector('[aria-hidden="true"].rounded-full')).toBeTruthy();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('скелетоны видны на фоне экрана: фигуры на поверхности карточки или цвета поверхности', () => {
    const { container } = render(
      <>
        <Skeleton screen className="h-4" />
        <SpecialistCardSkeleton />
        <JobCardSkeleton photos />
        <RowsSkeleton rows={2} leading="icon" trailing />
        <TileSkeleton />
        <ChipSkeleton className="w-24" />
        <FieldSkeleton tall />
        <ChatSkeleton />
      </>,
    );
    // фон экрана — bg2, как у .skel: голая фигура прямо на нём не видна
    expect(container.firstElementChild?.className).toContain('bg-surface');
    for (const shape of container.querySelectorAll('span.bg-bg2')) {
      expect(shape.closest('.bg-surface, .bg-bg')).toBeTruthy();
    }
    // скринридер слышит статус загрузки экрана, а не фигуры
    for (const element of container.children) {
      expect(
        element.getAttribute('aria-hidden') === 'true' ||
          element.querySelector(':scope > [aria-hidden="true"]') !== null,
      ).toBe(true);
    }
  });
});

describe('отклик на нажатие (только CSS)', () => {
  it('кнопки и плитки сжимаются, кроме отключённых; строки подсвечиваются; бегунок едет transform', () => {
    render(
      <>
        <Button>Откликнуться</Button>
        <Tile label="Уборка" icon="broom" href="/c/cleaning" />
        <Group>
          <Row title="Настройки" href="/settings" />
          <Row title="Версия" />
        </Group>
        <Switch checked onChange={() => {}} label="Уведомления" />
      </>,
    );
    const press = 'press';
    expect(screen.getByRole('button', { name: 'Откликнуться' }).className).toContain(press);
    expect(screen.getByRole('link', { name: 'Уборка' }).className).toContain(press);
    expect(screen.getByRole('link', { name: 'Настройки' }).className).toContain('press-row');
    // статичная строка не нажимается — и не подсвечивается
    expect(screen.getByText('Версия').closest('div')?.className).not.toContain('press');
    const knob = screen.getByRole('switch', { name: 'Уведомления' }).firstElementChild;
    expect(knob?.className).toContain('translate-x-5');
    expect(knob?.className).toContain('slide');
    expect(knob?.className).not.toContain('left-5.5');
  });
});
