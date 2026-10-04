// React-обвязка порта: провайдер (адаптер создаётся один раз в app/) и хуки экранов.
import type { ReactNode } from 'react';
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import type { BottomButtonState, ColorScheme, Platform } from './types.ts';

/**
 * Обработчики «Назад»: срабатывает самый поздний по порядку рендера (шторка поверх экрана).
 * Эффекты React идут от детей к родителю, поэтому порядок берём из рендера, а не из эффекта.
 * Кнопка не нативная (браузер, 8.1) — её рисует оболочка по `visible` и нажимает `press`.
 */
class BackStack {
  private readonly entries: { order: number; run: () => void }[] = [];
  private readonly listeners = new Set<() => void>();
  private readonly platform: Platform;
  private seq = 0;

  constructor(platform: Platform) {
    this.platform = platform;
    platform.backButton.onClick(this.press);
  }

  nextOrder(): number {
    this.seq += 1;
    return this.seq;
  }

  push(order: number, run: () => void): () => void {
    const entry = { order, run };
    this.entries.push(entry);
    this.changed();
    return () => {
      this.entries.splice(this.entries.indexOf(entry), 1);
      this.changed();
    };
  }

  press = (): void => {
    const top = [...this.entries].sort((a, b) => b.order - a.order)[0];
    top?.run();
  };

  visible = (): boolean => this.entries.length > 0;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private changed(): void {
    this.platform.backButton.setVisible(this.entries.length > 0);
    for (const listener of this.listeners) listener();
  }
}

/** Подтверждение закрытия включено, пока есть хотя бы один потребитель. */
class ClosingGate {
  private count = 0;
  private readonly platform: Platform;

  constructor(platform: Platform) {
    this.platform = platform;
  }

  acquire(): () => void {
    this.count += 1;
    if (this.count === 1) this.platform.setClosingConfirmation(true);
    return () => {
      this.count -= 1;
      if (this.count === 0) this.platform.setClosingConfirmation(false);
    };
  }
}

/** Тема, которую просит экран (просмотрщик S10 — тёмная): последний запрос побеждает. */
class SchemeOverride {
  private readonly requests: ColorScheme[] = [];
  private readonly listeners = new Set<() => void>();

  request(scheme: ColorScheme): () => void {
    this.requests.push(scheme);
    this.emit();
    return () => {
      this.requests.splice(this.requests.lastIndexOf(scheme), 1);
      this.emit();
    };
  }

  current = (): ColorScheme | null => this.requests.at(-1) ?? null;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

interface PlatformContextValue {
  platform: Platform;
  back: BackStack;
  closing: ClosingGate;
  scheme: SchemeOverride;
}

const PlatformContext = createContext<PlatformContextValue | null>(null);

export function PlatformProvider({
  platform,
  children,
}: {
  platform: Platform;
  children: ReactNode;
}) {
  const value = useMemo(
    () => ({
      platform,
      back: new BackStack(platform),
      closing: new ClosingGate(platform),
      scheme: new SchemeOverride(),
    }),
    [platform],
  );
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

function useCtx(): PlatformContextValue {
  const ctx = useContext(PlatformContext);
  if (!ctx) throw new Error('PlatformProvider не найден');
  return ctx;
}

/** Последнее значение без перезапуска эффектов, которые его вызывают. */
function useLatest<T>(value: T): { readonly current: T } {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}

export function usePlatform(): Platform {
  return useCtx().platform;
}

export interface BottomButtonProps {
  text: string;
  onClick: () => void;
  visible?: boolean;
  enabled?: boolean;
  loading?: boolean;
  color?: string;
  textColor?: string;
  shine?: boolean;
  position?: BottomButtonState['position'];
}

function useBottomButton(
  kind: 'mainButton' | 'secondaryButton',
  props: BottomButtonProps,
): { native: boolean } {
  const button = usePlatform()[kind];
  const onClick = useLatest(props.onClick);
  const { text, visible = true, enabled = true, loading = false } = props;
  const { color, textColor, shine, position } = props;

  useEffect(() => button.onClick(() => onClick.current()), [button, onClick]);
  useEffect(() => {
    button.set({ text, visible, enabled, loading, color, textColor, shine, position });
  }, [button, text, visible, enabled, loading, color, textColor, shine, position]);
  useEffect(() => () => button.set({ visible: false, loading: false }), [button]);
  return { native: button.native };
}

/** MainButton Telegram; в браузере — состояние для кнопки в контенте. */
export function useMainButton(props: BottomButtonProps): { native: boolean } {
  return useBottomButton('mainButton', props);
}

/** SecondaryButton; до Bot API 7.10 `native: false` — экран рисует кнопку в контенте. */
export function useSecondaryButton(props: BottomButtonProps): { native: boolean } {
  return useBottomButton('secondaryButton', props);
}

/** Состояние нижней кнопки для отрисовки в контенте, когда `native: false`. */
export function useBottomButtonState(kind: 'main' | 'secondary'): BottomButtonState & {
  native: boolean;
  click: () => void;
} {
  const button = usePlatform()[kind === 'main' ? 'mainButton' : 'secondaryButton'];
  const state = useSyncExternalStore(button.subscribe, button.getState, button.getState);
  return { ...state, native: button.native, click: button.click };
}

/** Кнопка «Назад» для отрисовки в контенте, когда `native: false` (браузер): видна, пока на экране
 *  есть обработчик «Назад»; нажатие — как нажатие кнопки Telegram. */
export function useBackButtonState(): { visible: boolean; native: boolean; click: () => void } {
  const { platform, back } = useCtx();
  const visible = useSyncExternalStore(back.subscribe, back.visible, back.visible);
  return { visible, native: platform.backButton.native, click: back.press };
}

/** «Назад»: пока хук смонтирован с обработчиком, кнопка видна; последняя шторка закрывается первой. */
export function useBackButton(handler: (() => void) | null): void {
  const { back } = useCtx();
  const [order] = useState(() => back.nextOrder());
  const latest = useLatest(handler);
  const active = handler !== null;
  useEffect(
    () => (active ? back.push(order, () => latest.current?.()) : undefined),
    [back, order, active, latest],
  );
}

/** Подтверждение закрытия, пока есть несохранённые изменения. */
export function useClosingConfirmation(enabled: boolean): void {
  const { closing } = useCtx();
  useEffect(() => (enabled ? closing.acquire() : undefined), [closing, enabled]);
}

export function useColorScheme(): ColorScheme {
  const { theme } = usePlatform();
  return useSyncExternalStore(theme.onChange, theme.colorScheme, theme.colorScheme);
}

export interface ChromeColors {
  header: string;
  background: string;
  bottomBar: string;
}

/** `data-theme` на <html> и цвета шапки, фона и нижней панели клиента Telegram. */
export function applyTheme(
  platform: Platform,
  scheme: ColorScheme,
  chrome?: Record<ColorScheme, ChromeColors>,
): void {
  document.documentElement.dataset.theme = scheme;
  const colors = chrome?.[scheme];
  if (!colors) return;
  platform.theme.setHeaderColor(colors.header);
  platform.theme.setBackgroundColor(colors.background);
  platform.theme.setBottomBarColor(colors.bottomBar);
}

/**
 * `data-theme` на <html> по colorScheme Telegram и цвета клиента — при смене темы и запросе экрана.
 * Тему запуска точка сборки ставит сама до первого кадра (`applyTheme`): эффект — уже после него.
 * Пока экран просит свою тему (`useColorSchemeOverride`), — она.
 */
export function useThemeSync(chrome?: Record<ColorScheme, ChromeColors>): ColorScheme {
  const { platform, scheme: override } = useCtx();
  const telegram = useColorScheme();
  const requested = useSyncExternalStore(override.subscribe, override.current, override.current);
  const scheme = requested ?? telegram;
  useEffect(() => applyTheme(platform, scheme, chrome), [platform, scheme, chrome]);
  return scheme;
}

/** Экран в своей теме, пока смонтирован: просмотрщик работ S10 — на тёмном фоне при любой теме. */
export function useColorSchemeOverride(scheme: ColorScheme): void {
  const { scheme: override } = useCtx();
  useEffect(() => override.request(scheme), [override, scheme]);
}
