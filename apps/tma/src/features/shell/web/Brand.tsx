// Знак «Соседей» вне Telegram (8.1): плашка с первой буквой названия и вордмарк Unbounded — как на
// S01. Малый — в шапке браузерной оболочки, крупный — в hero корневой страницы. Только CSS и
// текст: ни байта картинок. Плашка декоративная — название читается вордмарком рядом.
import { useTranslation } from '@sosed/i18n';

/** Шапка: плашка 24 × 24 с радиусом 7, «С» Unbounded 600 13 px и «Соседи» Unbounded 600 16/20. */
export function BrandMark() {
  const { t } = useTranslation();
  const name = t('app.name');
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className="flex size-6 shrink-0 items-center justify-center rounded-[7px] bg-accent font-display text-[13px] leading-none font-semibold text-accent-ink"
      >
        {name.charAt(0)}
      </span>
      <span className="font-display text-[16px] leading-5 font-semibold text-text">{name}</span>
    </span>
  );
}

/** Hero корневой страницы — блок S01: плашка 72 и H1 «Соседи» Unbounded 28/34. */
export function BrandHero() {
  const { t } = useTranslation();
  const name = t('app.name');
  return (
    <>
      <span
        aria-hidden="true"
        className="flex size-18 items-center justify-center rounded-sheet bg-accent font-display text-avatar-xl text-accent-ink"
      >
        {name.charAt(0)}
      </span>
      <h1 className="m-0 font-display text-h1-xl">{name}</h1>
    </>
  );
}
