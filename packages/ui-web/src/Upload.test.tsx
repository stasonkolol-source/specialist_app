// Плитки загрузки (2.1): выбор файлов, прогресс, сбой; превью локального файла. Тексты — фикстуры.
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Photo } from './Photo.tsx';
import { a11yViolations } from './testing/a11y.ts';
import { AddTile, UploadTile } from './Upload.tsx';

describe('AddTile', () => {
  it('открывает выбор файла и отдаёт выбранные файлы', async () => {
    const onFiles = vi.fn();
    const { container } = render(
      <AddTile label="Фото или видео" accept="image/*,video/mp4" multiple onFiles={onFiles} />,
    );
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    const click = vi.spyOn(input, 'click');

    fireEvent.click(screen.getByRole('button', { name: 'Фото или видео' }));
    const photo = new File(['a'], 'a.jpg', { type: 'image/jpeg' });
    fireEvent.change(input, { target: { files: [photo] } });

    expect(click).toHaveBeenCalledOnce();
    expect(input.accept).toBe('image/*,video/mp4');
    expect(input.multiple).toBe(true);
    expect(onFiles).toHaveBeenCalledWith([photo]);
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('пустой выбор (отменили диалог) ничего не добавляет', () => {
    const onFiles = vi.fn();
    const { container } = render(
      <AddTile label="Добавить" icon="camera" accept="image/*" onFiles={onFiles} />,
    );

    fireEvent.change(container.querySelector('input[type=file]') as HTMLInputElement, {
      target: { files: [] },
    });

    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe('UploadTile', () => {
  it('загрузка: подпись и полоса по доле', async () => {
    const { container } = render(
      <UploadTile state="uploading" progress={0.64} label="Загрузка 64%" className="h-28" />,
    );

    expect(screen.getByRole('status').textContent).toBe('Загрузка 64%');
    expect(container.querySelector('i')?.getAttribute('style')).toContain('width: 64%');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('компактная плитка показывает процент, подпись — скринридеру', () => {
    render(<UploadTile state="uploading" progress={0.5} label="Загрузка 50%" compact />);

    expect(screen.getByText('50%').getAttribute('aria-hidden')).toBe('true');
    expect(screen.getByText('Загрузка 50%').className).toContain('sr-only');
  });

  it('сбой: «Повторить» и «Убрать»', async () => {
    const onRetry = vi.fn();
    const onRemove = vi.fn();
    const { container } = render(
      <UploadTile
        state="failed"
        label="Не загрузилось"
        onRetry={onRetry}
        retryLabel="Повторить"
        onRemove={onRemove}
        removeLabel="Убрать"
      />,
    );

    expect(screen.getByRole('alert').textContent).toContain('Не загрузилось');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Убрать' }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledOnce();
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('отклонённый файл повторить нельзя — только убрать', () => {
    render(
      <UploadTile
        state="failed"
        label="Файл не подходит"
        retryLabel="Повторить"
        onRemove={() => {}}
        removeLabel="Убрать"
      />,
    );

    expect(screen.queryByRole('button', { name: 'Повторить' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Убрать' })).toBeTruthy();
  });
});

describe('Photo с локальным файлом', () => {
  afterEach(() => {
    Reflect.deleteProperty(URL, 'createObjectURL');
    Reflect.deleteProperty(URL, 'revokeObjectURL');
  });

  it('показывает превью и отзывает ссылку, когда фото уходит с экрана', () => {
    const revoke = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: () => 'blob:preview',
    });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke });

    const { unmount } = render(<Photo file={new Blob(['p'])} alt="Кухня" className="size-18" />);

    expect(screen.getByRole('img', { name: 'Кухня' }).getAttribute('src')).toBe('blob:preview');
    unmount();
    expect(revoke).toHaveBeenCalledWith('blob:preview');
  });
});

describe('Photo с сервера', () => {
  const variants = [320, 800, 1600].map((width) => ({
    url: `https://cdn.test/m/1/${width}.webp`,
    width,
  }));

  it('сначала размытый ThumbHash, потом вариант по ширине на экране', async () => {
    const { container } = render(
      <Photo
        alt="Кухня"
        variants={variants}
        placeholder="XRgODZpwd4dxiIiHiHiIh3iACPeI"
        sizes="33vw"
        className="h-28"
      />,
    );
    const frame = container.firstElementChild as HTMLElement;
    const img = screen.getByRole('img', { name: 'Кухня' });

    expect(frame.style.backgroundImage).toContain('data:image/png');
    expect(img.getAttribute('srcset')).toBe(
      'https://cdn.test/m/1/320.webp 320w, https://cdn.test/m/1/800.webp 800w, https://cdn.test/m/1/1600.webp 1600w',
    );
    expect(img.getAttribute('sizes')).toBe('33vw');
    expect(img.getAttribute('src')).toBe('https://cdn.test/m/1/800.webp');
    expect(img.className).toContain('opacity-0');
    fireEvent.load(img);
    expect(img.className).toContain('opacity-100');
    // после загрузки превью убрано: не просвечивает сквозь прозрачные PNG
    expect((container.firstElementChild as HTMLElement).style.backgroundImage).toBe('');
    expect(await a11yViolations(container)).toEqual([]);
  });

  it('не загрузилось — снова штриховка с подписью, а не пустая рамка', () => {
    render(<Photo alt="Кухня" variants={variants} placeholder="XRgODZpwd4dxiIiHiHiIh3iACPeI" />);

    fireEvent.error(screen.getByRole('img', { name: 'Кухня' }));

    const fallback = screen.getByRole('img', { name: 'Кухня' });
    expect(fallback.tagName).toBe('SPAN');
    expect(fallback.className).toContain('ph-stripes');
  });

  it('ширину на экране по умолчанию браузер берёт из раскладки', () => {
    render(<Photo alt="Кухня" variants={variants} />);

    expect(screen.getByRole('img', { name: 'Кухня' }).getAttribute('sizes')).toBe('auto, 100vw');
  });

  it('битый хэш не мешает показать фото', () => {
    const { container } = render(<Photo alt="Кухня" variants={variants} placeholder="%%%" />);

    expect((container.firstElementChild as HTMLElement).style.backgroundImage).toBe('');
    expect(screen.getByRole('img', { name: 'Кухня' })).toBeTruthy();
  });
});

describe('Photo с presigned-ссылками', () => {
  it('новая подпись той же картинки не перезагружает фото', () => {
    const signed = (signature: string) =>
      [320, 800].map((width) => ({
        url: `https://s3.test/m/1/${width}.webp?X-Sig=${signature}`,
        width,
      }));
    const { rerender } = render(<Photo alt="Кухня" variants={signed('a')} />);
    fireEvent.load(screen.getByRole('img', { name: 'Кухня' }));

    rerender(<Photo alt="Кухня" variants={signed('b')} />);

    expect(screen.getByRole('img', { name: 'Кухня' }).className).toContain('opacity-100');
  });
});
