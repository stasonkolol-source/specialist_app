// Рендер, поведение и доступность компонентов 0.19b. Тексты — данные фикстур.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { AvatarStack, Chip, Chips, Price } from './Chips.tsx';
import { Banner, EmptyState, ProgressBar, Skeleton, Stars, Steps, Toast } from './Feedback.tsx';
import { Checkbox, Option, RadioGroup, Segmented, Switch } from './form/Choice.tsx';
import { Field, Input, SearchField, Textarea } from './form/Field.tsx';
import { Badge } from './Badge.tsx';
import { LinkButton } from './Button.tsx';
import { FeedRow, Group, Row, RowIcon, Tile, Tiles, UnreadDot } from './Group.tsx';
import { Photo } from './Photo.tsx';
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
});
