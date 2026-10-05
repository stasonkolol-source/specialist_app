// Точка на карте S20b (Q28, вариант A) — ленивым чанком: MapLibre, pmtiles и стиль Protomaps в первый
// экран не попадают. Карта на весь экран поверх S20b, метка стоит в центре — двигается карта; под
// картой — район центра (useCentreDistrict). «Выбрать» — MainButton (в браузере — кнопка в контенте),
// её ведёт WhenForm: одна кнопка на два владельца («Далее» шага и «Выбрать») путала бы нажатия.
// Сюда приходит только текущий выбор (onPickChange). «Назад» Telegram, «Отмена» и Escape закрывают
// карту без изменений. Карта не поднялась (нет WebGL, ассеты не загрузились) — подсказка выбрать
// район из списка.
import 'maplibre-gl/dist/maplibre-gl.css';

import type { DistrictOut, PointOut } from '@sosed/api-client';
import { useLocale, useTranslation } from '@sosed/i18n';
import {
  useBackButton,
  useBottomButtonState,
  useColorScheme,
  useInsets,
  usePlatform,
} from '@sosed/platform';
import { Button, Heading, Icon, LinkButton, cx } from '@sosed/ui-web';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { Map as MapLibre, addProtocol, setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol } from 'pmtiles';
import type { KeyboardEvent } from 'react';
import { useEffect, useId, useRef, useState } from 'react';

import { useLocate } from '../../shared/location.ts';
import type { MapPick } from './config.ts';
import { MAP_BOUNDS, absoluteBase, mapStyle } from './style.ts';
import { useCentreDistrict } from './useCentreDistrict.ts';

/** Мельче — город целиком уже не помещается в рамку тайлов. */
const MIN_ZOOM = 10;
/** Тайлы до 15-го зума, дальше MapLibre растягивает векторы — дом виден крупно. */
const MAX_ZOOM = 18;
/** «Я здесь» — до уровня улиц, если карта была мельче. */
const HERE_ZOOM = 15;
/** Высота кнопки в контенте (ContentMainButton, BUTTON_AREA): в браузере она поверх карты. */
const BUTTON_SPACE = 76;

/** Авторы данных и стиля — названия не переводятся. */
const ATTRIBUTION = [
  { name: 'OpenStreetMap', href: 'https://www.openstreetmap.org/copyright' },
  { name: 'Protomaps', href: 'https://protomaps.com' },
] as const;

const reducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

let registered = false;

/** Протокол pmtiles:// и воркер MapLibre — один раз на страницу. Воркер — свой файл сборки (тот же
 *  origin): CSP пускает его без blob:. */
function registerOnce(): void {
  if (registered) return;
  registered = true;
  setWorkerUrl(workerUrl);
  addProtocol('pmtiles', new Protocol().tile);
}

const inBounds = ({ lat, lon }: PointOut) => {
  const [[west, south], [east, north]] = MAP_BOUNDS;
  return lon > west && lon < east && lat > south && lat < north;
};

export interface MapPickerProps {
  /** База ассетов карты (VITE_MAP_ASSETS_URL). */
  base: string;
  cityId: number;
  /** Районы списка «Где»: выбор на карте — один из них. */
  districts: readonly DistrictOut[];
  /** Где открыть: центр выбранного района (крупнее) или города. */
  start: { point: PointOut; zoom: number };
  /** Выбор под меткой для «Выбрать»: null — выбирать пока нечего (карта двигается, точка за
   *  городом, район не определился). */
  onPickChange: (pick: MapPick | null) => void;
  onCancel: () => void;
}

export function MapPicker({
  base,
  cityId,
  districts,
  start,
  onPickChange,
  onCancel,
}: MapPickerProps) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const locale = useLocale();
  const scheme = useColorScheme();
  const platform = usePlatform();
  const insets = useInsets();
  const button = useBottomButtonState('main');
  const locate = useLocate();
  const titleId = useId();
  const dialog = useRef<HTMLElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [failed, setFailed] = useState(false);
  const [moving, setMoving] = useState(false);
  const [centre, setCentre] = useState(start.point);
  const [locating, setLocating] = useState(false);
  const [hereFailed, setHereFailed] = useState(false);
  const found = useCentreDistrict(cityId, centre, districts);
  const status = moving ? ({ kind: 'pending' } as const) : found;
  // район — объект из списка «Где» (тот же между рендерами), точка — числа: эффект ниже зовёт
  // onPickChange только при смене выбора, а не на каждом рендере
  const picked = !failed && status.kind === 'found' ? status.district : null;
  const { lat, lon } = found.point;

  useBackButton(onCancel);

  // жест вниз по карте в Telegram сворачивал бы Mini App
  useEffect(() => {
    platform.setVerticalSwipes(false);
    return () => platform.setVerticalSwipes(true);
  }, [platform]);

  // фокус — в диалог, после закрытия — туда, откуда открыли (как у Sheet)
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus({ preventScroll: true });
    return () => opener?.focus();
  }, []);

  useEffect(() => {
    onPickChange(picked ? { lat, lon, district: picked } : null);
  }, [picked, lat, lon, onPickChange]);

  // карта создаётся один раз; тема и язык меняют стиль ниже
  const initial = useRef({ base, scheme, locale, start, title: t('create.when.map.title') });
  useEffect(() => {
    const element = container.current;
    if (!element) return undefined;
    const { base: assets, scheme: flavor, locale: lang, start: at, title } = initial.current;
    let instance: MapLibreMap;
    try {
      registerOnce();
      instance = new MapLibre({
        container: element,
        style: mapStyle({
          base: absoluteBase(assets, location.href),
          scheme: flavor,
          locale: lang,
        }),
        center: [at.point.lon, at.point.lat],
        zoom: at.zoom,
        minZoom: MIN_ZOOM,
        maxZoom: MAX_ZOOM,
        maxBounds: MAP_BOUNDS,
        // подпись OpenStreetMap и Protomaps рисует экран: у контрола MapLibre мелкая кнопка
        attributionControl: false,
        // карта для точки, не для осмотра: без поворота и наклона север всегда сверху
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        fadeDuration: reducedMotion() ? 0 : 300,
        locale: { 'Map.Title': title },
      });
    } catch {
      // нет WebGL — MapLibre бросает из конструктора; отказ — как событие карты, после эффекта
      void Promise.resolve().then(() => setFailed(true));
      return undefined;
    }
    instance.touchZoomRotate.disableRotation();
    instance.keyboard.disableRotation();
    let loaded = false;
    instance.on('load', () => {
      loaded = true;
    });
    // стиль, тайлы или шрифты не загрузились до первого кадра — карты нет; позже — тайл, и только
    instance.on('error', () => {
      if (!loaded) setFailed(true);
    });
    instance.on('movestart', () => setMoving(true));
    instance.on('moveend', () => {
      const { lat, lng } = instance.getCenter();
      setCentre({ lat, lon: lng });
      setMoving(false);
    });
    map.current = instance;
    return () => {
      map.current = null;
      instance.remove();
    };
  }, []);

  const styled = useRef(`${scheme}:${locale}`);
  useEffect(() => {
    const key = `${scheme}:${locale}`;
    if (styled.current === key) return;
    styled.current = key;
    map.current?.setStyle(mapStyle({ base: absoluteBase(base, location.href), scheme, locale }));
  }, [base, scheme, locale]);

  const here = async () => {
    setHereFailed(false);
    setLocating(true);
    const point = await locate();
    setLocating(false);
    const instance = map.current;
    if (!instance || !point || !inBounds(point)) {
      platform.haptics.notification('warning');
      setHereFailed(true);
      return;
    }
    const camera = {
      center: [point.lon, point.lat] as [number, number],
      zoom: Math.max(instance.getZoom(), HERE_ZOOM),
    };
    if (reducedMotion()) instance.jumpTo(camera);
    else instance.easeTo({ ...camera, duration: 400 });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    onCancel();
  };

  const headline = failed
    ? t('create.when.map.unavailable')
    : hereFailed && status.kind !== 'found'
      ? t('create.when.map.hereFailed')
      : status.kind === 'found'
        ? status.district.name
        : status.kind === 'outside'
          ? t('create.when.map.outside')
          : status.kind === 'failed'
            ? t('create.when.map.failed')
            : t('create.when.locating');

  return (
    <section
      ref={dialog}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-40 mx-auto flex max-w-lg flex-col bg-bg outline-none"
      style={{ paddingTop: insets.top, paddingLeft: insets.left, paddingRight: insets.right }}
    >
      <header className="flex min-h-14 shrink-0 items-center justify-between gap-2 pr-2 pl-4">
        <Heading variant="h2" as="h2" id={titleId}>
          {t('create.when.map.title')}
        </Heading>
        <LinkButton onClick={onCancel}>{t('create.when.map.cancel')}</LinkButton>
      </header>
      <div className="relative min-h-0 flex-1 overflow-hidden bg-bg2">
        {/* MapLibre ставит контейнеру position: relative (.maplibregl-map) — место задаёт обёртка */}
        <div className="absolute inset-0">
          <div ref={container} className="size-full" />
        </div>
        {!failed && (
          <>
            {/* метка — над центром карты: острие ровно в центре, при движении приподнимается */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-text/30"
            />
            <svg
              aria-hidden="true"
              viewBox="0 0 36 46"
              width="36"
              height="46"
              className={cx(
                'pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-full text-accent drop-shadow-md motion-safe:transition-transform',
                moving && '-translate-y-[calc(100%+8px)]',
              )}
            >
              <path
                d="M18 45S4 28.6 4 17.6a14 14 0 0 1 28 0C32 28.6 18 45 18 45Z"
                fill="currentColor"
                className="stroke-surface"
                strokeWidth="2"
              />
              <circle cx="18" cy="17.5" r="5.5" className="fill-accent-ink" />
            </svg>
            <Button
              variant="outline"
              icon="locate"
              disabled={locating}
              aria-busy={locating || undefined}
              onClick={() => void here()}
              className="absolute top-3 right-3 shadow-pin"
            >
              {t('create.when.map.here')}
            </Button>
            {/* подпись данных обязательна (ODbL): видна всегда, не за кнопкой */}
            <p className="absolute bottom-0 left-0 m-0 flex gap-1 rounded-tr-[8px] bg-surface/85 px-2 py-0.5 text-[11px] leading-4 text-text2">
              ©
              {ATTRIBUTION.map(({ name, href }, index) => (
                <a
                  key={href}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-inherit underline"
                >
                  {index < ATTRIBUTION.length - 1 ? `${name},` : name}
                </a>
              ))}
            </p>
          </>
        )}
      </div>
      <div
        className="flex shrink-0 items-start gap-3 px-4 pt-3"
        style={{
          paddingBottom: (button.native ? 12 : BUTTON_SPACE) + insets.bottom,
        }}
      >
        <Icon name="pin" className="mt-0.5 shrink-0 text-accent" />
        {/* район под меткой — вежливо для скринридера; пока карта двигается, область занята */}
        <div role="status" aria-busy={status.kind === 'pending' || undefined} className="min-w-0">
          <p className="m-0 text-title">{headline}</p>
          {!failed && <p className="m-0 text-cap text-text2">{t('create.when.map.hint')}</p>}
          {!failed && status.kind === 'failed' && (
            <LinkButton onClick={status.retry} className="-ml-2">
              {common('action.retry')}
            </LinkButton>
          )}
        </div>
      </div>
    </section>
  );
}
