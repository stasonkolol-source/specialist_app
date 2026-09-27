/* eslint-disable sosed/no-jsx-literal -- страница спайка 0.24 только для dev: не локализуется и
   удаляется в 2.1 вместе с эндпоинтами /__spike */
// Спайк 0.24 «загрузка медиа из WebView» (DEVELOPMENT_PLAN 0.24): камера и галерея, мультивыбор,
// HEIC, видео через multipart, прогресс, повтор после обрыва. Лог копируется в записку
// docs/spikes/0.24-webview-upload.md (таблица «устройство × сценарий»).
import { apiFetch } from '@sosed/api-client';
import { usePlatform } from '@sosed/platform';
import { Button, Heading, ProgressBar, Text } from '@sosed/ui-web';
import type { ChangeEvent } from 'react';
import { useRef, useState } from 'react';

import type { SpikeApi, StoredObject } from './uploader.ts';
import { UploadTask, xhrPut } from './uploader.ts';

const BASE = '/api/v1/__spike/uploads';
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

const api: SpikeApi = {
  start: (body) => apiFetch(BASE, json(body)),
  sign: (body) => apiFetch(`${BASE}/sign`, json(body)),
  complete: (body) => apiFetch(`${BASE}/complete`, json(body)),
  abort: (body) => apiFetch(`${BASE}/abort`, json(body)),
  head: (key) => apiFetch(`${BASE}?${new URLSearchParams({ key })}`),
};

type Status = 'uploading' | 'done' | 'error';

interface Item {
  id: number;
  task: UploadTask;
  status: Status;
  loaded: number;
  seconds?: number;
  stored?: StoredObject;
  error?: string;
}

/** Камера — один снимок; галерея — мультивыбор (iOS может сам перекодировать HEIC в JPEG);
 *  «Файлы» явно разрешают HEIC — проверяем, придёт ли оригинал. */
const SOURCES = [
  {
    id: 'camera',
    label: 'Камера',
    accept: 'image/*,video/*',
    multiple: false,
    capture: 'environment',
    variant: 'primary',
  },
  {
    id: 'gallery',
    label: 'Галерея',
    accept: 'image/*,video/*',
    multiple: true,
    capture: undefined,
    variant: 'secondary',
  },
  {
    id: 'heic',
    label: 'Файлы (HEIC как есть)',
    accept: 'image/heic,image/heif,.heic,.heif,image/*,video/*',
    multiple: true,
    capture: undefined,
    variant: 'secondary',
  },
] as const;

const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;
const clock = () => new Date().toISOString().slice(11, 19);

export function UploadSpikeScreen() {
  const platform = usePlatform();
  const [items, setItems] = useState<Item[]>([]);
  const [lines, setLines] = useState<string[]>([]);
  const nextId = useRef(1);
  const controllers = useRef(new Map<number, AbortController>());
  const inputs = useRef(new Map<string, HTMLInputElement>());

  const log = (message: string) => setLines((prev) => [...prev, `${clock()} ${message}`]);
  const patch = (id: number, change: Partial<Item>) =>
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...change } : item)));

  const run = async (item: Item) => {
    const controller = new AbortController();
    controllers.current.set(item.id, controller);
    patch(item.id, { status: 'uploading', error: undefined });
    try {
      const { stored, ms } = await item.task.run(controller.signal);
      const seconds = ms / 1000;
      patch(item.id, { status: 'done', stored, seconds, loaded: item.task.file.size });
      log(
        `${item.task.file.name}: HEAD ${stored.size} B ${stored.content_type} за ${seconds.toFixed(1)} с`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      patch(item.id, { status: 'error', error: message });
      log(`${item.task.file.name}: ошибка — ${message}`);
    } finally {
      controllers.current.delete(item.id);
    }
  };

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    event.target.value = '';
    for (const file of files) {
      const id = nextId.current++;
      log(`выбран ${file.name}: type="${file.type}" ${mb(file.size)}`);
      const task = new UploadTask(file, { api, put: xhrPut, log }, (loaded) =>
        patch(id, { loaded }),
      );
      const item: Item = { id, task, status: 'uploading', loaded: 0 };
      setItems((prev) => [...prev, item]);
      void run(item);
    }
  };

  const cancel = async (item: Item) => {
    controllers.current.get(item.id)?.abort();
    await item.task.abort().catch(() => undefined);
    log(`${item.task.file.name}: отменено`);
  };

  const { launch } = platform;
  const env = `${launch.platform} ${launch.version} · ${navigator.userAgent}`;

  return (
    <section className="flex flex-col gap-3 px-4 pt-4 pb-8">
      <Heading variant="h1">Спайк 0.24: загрузка</Heading>
      <Text variant="cap">{env}</Text>
      <div className="flex flex-wrap gap-2">
        {SOURCES.map((source) => (
          <Button
            key={source.id}
            size="sm"
            variant={source.variant}
            onClick={() => inputs.current.get(source.id)?.click()}
          >
            {source.label}
          </Button>
        ))}
      </div>
      {SOURCES.map((source) => (
        <input
          key={source.id}
          ref={(node) => {
            if (node) inputs.current.set(source.id, node);
          }}
          type="file"
          accept={source.accept}
          multiple={source.multiple}
          capture={source.capture}
          hidden
          onChange={pick}
        />
      ))}

      {items.map((item) => {
        const { file } = item.task;
        return (
          <article key={item.id} className="flex flex-col gap-2 rounded-lg border p-3">
            <Text>
              {file.name} · {item.task.contentType || 'тип неизвестен'} · {mb(file.size)}
              {item.task.plan?.upload_id ? ` · multipart ${item.task.plan.parts.length}` : ''}
            </Text>
            <ProgressBar value={item.loaded} max={file.size} label={file.name} />
            {item.status === 'uploading' && (
              <Button size="sm" variant="secondary" onClick={() => void cancel(item)}>
                Отменить
              </Button>
            )}
            {item.status === 'error' && (
              <>
                <Text variant="cap">{item.error}</Text>
                <Button size="sm" onClick={() => void run(item)}>
                  Повторить
                </Button>
              </>
            )}
            {item.stored && (
              <>
                <Text variant="cap">
                  HEAD: {item.stored.size} B, {item.stored.content_type}, {item.seconds?.toFixed(1)}{' '}
                  с
                </Text>
                {item.stored.content_type?.startsWith('video/') ? (
                  <video src={item.stored.url} controls muted playsInline className="max-h-60" />
                ) : (
                  <img src={item.stored.url} alt={file.name} className="max-h-60 object-contain" />
                )}
              </>
            )}
          </article>
        );
      })}

      <div className="flex gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void navigator.clipboard?.writeText([env, ...lines].join('\n'))}
        >
          Копировать лог
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setLines([])}>
          Очистить
        </Button>
      </div>
      <pre className="overflow-x-auto text-xs whitespace-pre-wrap">{lines.join('\n')}</pre>
    </section>
  );
}
