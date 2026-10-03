// S01 «Запуск» (DEVELOPMENT_PLAN 1.5b): вордмарк, скелетон главной и «Входим через Telegram…»,
// пока грузится client-config и идёт вход по initData. Рисуется до роутера и оболочки — отступы
// safe area ставит сам; фон — .scr.plain (bg), как на артборде. Экран не прокручивается: на
// низком экране (375×667) скелетон обрезается с растушёвкой, а статус входа остаётся внизу на виду.
import { useTranslation } from '@sosed/i18n';
import { useInsets } from '@sosed/platform';
import { ProgressBar, Skeleton, Text } from '@sosed/ui-web';

/** Отступы артборда: 72 сверху, 24 по бокам, 32 снизу. */
const PAD = { top: 72, side: 24, bottom: 32 };
const TILES = 6;

export function LaunchScreen({ progress }: { progress: number }) {
  // только общий неймспейс: он в первом чанке, а экран запуска не должен ждать загрузки текстов
  const { t } = useTranslation();
  const insets = useInsets();
  const name = t('app.name');
  return (
    <main
      className="mx-auto flex h-dvh max-w-lg flex-col gap-10 overflow-hidden bg-bg"
      style={{
        paddingTop: insets.top + PAD.top,
        paddingRight: insets.right + PAD.side,
        paddingBottom: insets.bottom + PAD.bottom,
        paddingLeft: insets.left + PAD.side,
      }}
    >
      <div className="flex shrink-0 flex-col items-center gap-3 text-center">
        <span
          aria-hidden="true"
          className="flex size-18 items-center justify-center rounded-sheet bg-accent font-display text-avatar-xl text-accent-ink"
        >
          {name.charAt(0)}
        </span>
        <h1 className="m-0 font-display text-h1-xl">{name}</h1>
        <Text secondary>{t('app.tagline')}</Text>
      </div>

      {/* скелетон главной: поиск, плитки категорий, карточка */}
      <div
        aria-hidden="true"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden mask-b-from-85%"
      >
        <Skeleton radius="panel" className="h-12 shrink-0" />
        <div className="grid shrink-0 grid-cols-3 gap-2">
          {Array.from({ length: TILES }, (_, i) => (
            <Skeleton key={i} radius="card" className="h-22" />
          ))}
        </div>
        <Skeleton radius="card" className="h-28 shrink-0" />
      </div>

      <div role="status" className="flex shrink-0 flex-col items-center gap-2">
        <div aria-hidden="true" className="w-40">
          <ProgressBar value={progress} max={1} label={t('app.signingIn')} />
        </div>
        <Text variant="cap">{t('app.signingIn')}</Text>
      </div>
    </main>
  );
}
