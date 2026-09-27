import type { Insets } from '@sosed/platform';
import { usePlatform } from '@sosed/platform';
import { useSyncExternalStore } from 'react';

const ZERO: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

/**
 * Отступы от краёв: safe area устройства плюс content safe area Telegram (шапка клиента в
 * fullscreen). Снимок кэшируется, чтобы useSyncExternalStore видел стабильный объект.
 */
export function useInsets(): Insets {
  const { viewport } = usePlatform();
  const cache = useSyncExternalStore(
    viewport.onChange,
    () => key(viewport),
    () => '',
  );
  return cache ? parse(cache) : ZERO;
}

const key = (viewport: { safeArea(): Insets; contentSafeArea(): Insets }): string => {
  const safe = viewport.safeArea();
  const content = viewport.contentSafeArea();
  return [
    safe.top + content.top,
    safe.right + content.right,
    safe.bottom + content.bottom,
    safe.left + content.left,
  ].join(',');
};

const parse = (value: string): Insets => {
  const [top = 0, right = 0, bottom = 0, left = 0] = value.split(',').map(Number);
  return { top, right, bottom, left };
};
