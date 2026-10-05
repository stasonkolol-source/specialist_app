// Точка сборки карты S20b: сам MapPicker (MapLibre, pmtiles, стиль) — своим чанком при первом
// открытии. Пока чанк качается — та же шапка с «Отменой» над пустой картой; «Назад» Telegram уже
// закрывает её, а не уводит на прошлый шаг. Чанк не скачался — карта закрывается, S20b подсказывает
// выбрать район из списка (onUnavailable).
import { useTranslation } from '@sosed/i18n';
import { useBackButton, useInsets } from '@sosed/platform';
import { Heading, LinkButton } from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { Component, Suspense, lazy, useId } from 'react';

import type { MapPickerProps } from './MapPicker.tsx';

const MapPicker = lazy(() =>
  import('./MapPicker.tsx').then((module) => ({ default: module.MapPicker })),
);

class ChunkBoundary extends Component<
  { onError: () => void; children: ReactNode },
  { failed: boolean }
> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override componentDidCatch(): void {
    this.props.onError();
  }

  override render(): ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}

function MapLoading({ onCancel }: { onCancel: () => void }) {
  const { t } = useTranslation('jobs');
  const titleId = useId();
  const insets = useInsets();
  useBackButton(onCancel);
  return (
    <section
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-busy="true"
      className="fixed inset-0 z-40 mx-auto flex max-w-lg flex-col bg-bg"
      style={{ paddingTop: insets.top }}
    >
      <header className="flex min-h-14 shrink-0 items-center justify-between gap-2 pr-2 pl-4">
        <Heading variant="h2" as="h2" id={titleId}>
          {t('create.when.map.title')}
        </Heading>
        <LinkButton onClick={onCancel}>{t('create.when.map.cancel')}</LinkButton>
      </header>
      <div className="flex-1 bg-bg2 motion-safe:animate-pulse" />
    </section>
  );
}

export function MapPickerHost({
  onUnavailable,
  ...props
}: MapPickerProps & { onUnavailable: () => void }) {
  return (
    <ChunkBoundary onError={onUnavailable}>
      <Suspense fallback={<MapLoading onCancel={props.onCancel} />}>
        <MapPicker {...props} />
      </Suspense>
    </ChunkBoundary>
  );
}
