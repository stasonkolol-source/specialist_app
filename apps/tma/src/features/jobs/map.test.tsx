// S20b «Указать на карте» (Q28): MapPicker целиком — ленивый чанк, район центра с задержкой,
// «Вне Нови-Сада», «Выбрать» MainButton и «Отмена». У jsdom нет WebGL: MapLibre — фейк, который
// двигается по команде теста, как после жеста человека.
import { setSession } from '@sosed/api-client';
import type { MockTelegram } from '@sosed/platform';
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mainButton, pressBackButton, pressMainButton, startApp } from '../../testing/app.tsx';
import { JobsBackend } from '../../testing/jobsBackend.ts';
import { jobsHandlers, server } from '../../testing/msw.ts';
import { useDraftStore } from './shared/draft.ts';

const { maps, FakeMap, webgl } = vi.hoisted(() => {
  type Handler = () => void;
  interface Camera {
    center: [number, number];
    zoom?: number;
  }
  const maps: InstanceType<typeof FakeMap>[] = [];
  /** false — у устройства нет WebGL: MapLibre бросает из конструктора. */
  const webgl = { value: true };
  class FakeMap {
    readonly options: { center: [number, number]; zoom: number; style: unknown };
    private center: { lng: number; lat: number };
    private zoom: number;
    private readonly handlers: Record<string, Handler[]> = {};
    readonly touchZoomRotate = { disableRotation: () => {} };
    readonly keyboard = { disableRotation: () => {} };
    readonly removed = { value: false };
    constructor(options: { center: [number, number]; zoom: number; style: unknown }) {
      if (!webgl.value) throw new Error('Failed to initialize WebGL');
      this.options = options;
      this.center = { lng: options.center[0], lat: options.center[1] };
      this.zoom = options.zoom;
      maps.push(this);
    }
    on(type: string, handler: Handler) {
      (this.handlers[type] ??= []).push(handler);
      return this;
    }
    emit(type: string) {
      for (const handler of this.handlers[type] ?? []) handler();
    }
    getCenter() {
      return this.center;
    }
    getZoom() {
      return this.zoom;
    }
    /** Жест человека: карта сдвинулась и остановилась. */
    pan(lat: number, lon: number) {
      this.emit('movestart');
      this.center = { lng: lon, lat };
      this.emit('moveend');
    }
    jumpTo({ center, zoom }: Camera) {
      this.zoom = zoom ?? this.zoom;
      this.pan(center[1], center[0]);
    }
    easeTo(camera: Camera) {
      this.jumpTo(camera);
    }
    setStyle() {}
    remove() {
      this.removed.value = true;
    }
  }
  return { maps, FakeMap, webgl };
});

vi.mock('maplibre-gl', () => ({ Map: FakeMap, addProtocol: vi.fn(), setWorkerUrl: vi.fn() }));

/** Точки: Лиман (в городе — фейк backend отвечает районом) и Каћ (в рамке карты, но за городом). */
const LIMAN = { lat: 45.2448, lon: 19.8451 };
const OUTSIDE = { lat: 45.3, lon: 19.98 };

let locateCalls: URLSearchParams[] = [];

beforeEach(() => {
  useDraftStore.setState({ draft: null, storage: null });
  vi.stubEnv('VITE_MAP_ASSETS_URL', '/map');
  maps.length = 0;
  webgl.value = true;
  locateCalls = [];
  server.use(...jobsHandlers(() => new JobsBackend()));
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith('/geo/districts/locate')) locateCalls.push(url.searchParams);
  });
});
afterEach(() => {
  server.events.removeAllListeners();
  vi.unstubAllEnvs();
  cleanup();
  setSession(null);
});

const click = (element: HTMLElement) =>
  act(async () => {
    fireEvent.click(element);
  });

/** S20a заполнен — на экране S20b. */
async function fillWhat(telegram: MockTelegram) {
  await screen.findByRole('textbox', { name: 'Коротко о задаче' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Коротко о задаче' }), {
    target: { value: 'Люстры' },
  });
  await screen.findByRole('button', { name: /^Мастер на час → Люстры и карнизы ?Изменить$/ });
  fireEvent.change(screen.getByRole('textbox', { name: 'Подробности' }), {
    target: { value: 'Потолок бетонный' },
  });
  await pressMainButton(telegram);
}

/** S20b после S20a, карта открыта и поднялась. */
async function openMap(): Promise<{ telegram: MockTelegram; map: InstanceType<typeof FakeMap> }> {
  const { telegram } = startApp('/jobs/new');
  await fillWhat(telegram);
  await click(await screen.findByRole('button', { name: 'Указать на карте' }));
  expect(await screen.findByRole('dialog', { name: 'Точка на карте' })).toBeTruthy();
  await waitFor(() => expect(maps).toHaveLength(1));
  const map = maps[0];
  if (!map) throw new Error('map not created');
  return { telegram, map };
}

/** Район под меткой — строка состояния в диалоге карты. */
const hint = () => within(screen.getByRole('dialog')).getByRole('status');

describe('S20b map picker', () => {
  it('opens on the city, resolves the centre after the map rests, «Выбрать» picks it', async () => {
    const { telegram, map } = await openMap();
    // район ещё не выбран — карта на центре города
    expect(map.options.center).toEqual([19.8335, 45.2671]);
    expect(map.options.zoom).toBe(12);
    // район центра города (фейк backend: всё в городе — Лиман)
    await waitFor(() => expect(hint().textContent).toContain('Лиман'));
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Выбрать', is_active: true }),
    );

    // три жеста подряд — один запрос: район спрашивают, когда карта постояла
    locateCalls = [];
    act(() => {
      map.pan(45.25, 19.84);
      map.pan(45.246, 19.844);
      map.pan(LIMAN.lat, LIMAN.lon);
    });
    expect(hint().textContent).toContain('Определяем район…');
    expect(hint().getAttribute('aria-busy')).toBe('true');
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ is_active: false }));
    await waitFor(() => expect(hint().textContent).toContain('Лиман'));
    expect(locateCalls).toHaveLength(1);
    expect(locateCalls[0]?.get('lat')).toBe(String(LIMAN.lat));
    expect(locateCalls[0]?.get('lon')).toBe(String(LIMAN.lon));
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Выбрать', is_active: true }),
    );

    await pressMainButton(telegram);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(map.removed.value).toBe(true);
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад, Лиман');
    expect(screen.getByText('Район определён: Лиман')).toBeTruthy();
    // точка нигде не хранится: в черновике — только район
    expect(JSON.stringify(useDraftStore.getState().draft)).not.toContain(String(LIMAN.lat));
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Далее' }));
  });

  it('says «Вне Нови-Сада» outside the city and keeps «Выбрать» off', async () => {
    const { telegram, map } = await openMap();
    act(() => map.pan(OUTSIDE.lat, OUTSIDE.lon));

    await waitFor(() => expect(hint().textContent).toContain('Вне Нови-Сада'));
    expect(hint().getAttribute('aria-busy')).toBeNull();
    await waitFor(() =>
      expect(mainButton(telegram)).toMatchObject({ text: 'Выбрать', is_active: false }),
    );
  });

  it('«Я здесь» moves the map to the device point', async () => {
    const { map } = await openMap();
    await click(screen.getByRole('button', { name: 'Я здесь' }));

    // точка устройства mock-платформы (в Лимане, ~100 м); к улицам, если карта была мельче
    await waitFor(() => expect(map.getCenter()).toEqual({ lat: 45.24, lng: 19.835 }));
    expect(map.getZoom()).toBe(15);
  });

  it('«Я здесь» without a device point asks to find the place; moving the map clears it', async () => {
    const { telegram } = startApp('/jobs/new', { location: null });
    await fillWhat(telegram);
    await click(await screen.findByRole('button', { name: 'Указать на карте' }));
    await waitFor(() => expect(maps).toHaveLength(1));
    await click(screen.getByRole('button', { name: 'Я здесь' }));

    await waitFor(() =>
      expect(hint().textContent).toContain(
        'Не получилось определить, где вы. Найдите место на карте.',
      ),
    );
    act(() => maps[0]?.pan(OUTSIDE.lat, OUTSIDE.lon));
    await waitFor(() => expect(hint().textContent).toContain('Вне Нови-Сада'));
  });

  it('closes without changes: Telegram «Назад» and «Отмена»', async () => {
    const { telegram, map } = await openMap();
    act(() => map.pan(LIMAN.lat, LIMAN.lon));
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ is_active: true }));

    await pressBackButton(telegram);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад');
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ text: 'Далее' }));

    await click(screen.getByRole('button', { name: 'Указать на карте' }));
    await click(await screen.findByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'Где' }).textContent).toBe('Нови-Сад');
  });

  it('opens on the chosen district', async () => {
    const { telegram, map } = await openMap();
    act(() => map.pan(LIMAN.lat, LIMAN.lon));
    await waitFor(() => expect(mainButton(telegram)).toMatchObject({ is_active: true }));
    await pressMainButton(telegram);

    await click(screen.getByRole('button', { name: 'Указать на карте' }));
    await waitFor(() => expect(maps).toHaveLength(2));
    expect(maps[1]?.options.zoom).toBe(14);
  });

  it('asks to retry when the district lookup fails', async () => {
    server.use(
      http.get('*/api/v1/geo/districts/locate', () => HttpResponse.json({}, { status: 503 })),
    );
    const { map } = await openMap();
    act(() => map.pan(LIMAN.lat, LIMAN.lon));

    await waitFor(() =>
      expect(hint().textContent).toContain('Не получилось определить район. Попробуйте ещё раз.'),
    );
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy();
  });

  it('without WebGL says to choose from the list', async () => {
    webgl.value = false;
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);
    await click(await screen.findByRole('button', { name: 'Указать на карте' }));

    await waitFor(() =>
      expect(hint().textContent).toBe('Карта не загрузилась. Выберите район из списка.'),
    );
    expect(screen.queryByRole('button', { name: 'Я здесь' })).toBeNull();
    expect(mainButton(telegram)).toMatchObject({ is_active: false });
  });
});

describe('S20b without the map', () => {
  it('has no «Указать на карте» when VITE_MAP_ASSETS_URL is empty', async () => {
    vi.stubEnv('VITE_MAP_ASSETS_URL', '');
    const { telegram } = startApp('/jobs/new');
    await fillWhat(telegram);

    expect(await screen.findByRole('button', { name: 'Определить по геолокации' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Указать на карте' })).toBeNull();
  });
});
