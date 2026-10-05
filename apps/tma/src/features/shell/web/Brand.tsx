// Знак «Соседей» вне Telegram (8.1): плашка с первой буквой названия и вордмарк Unbounded — как на
// S01. Малый — в шапке браузерной оболочки, крупный — в hero корневой страницы. Только CSS и
// текст: ни байта картинок. Плашка декоративная — название читается вордмарком рядом.
import { useTranslation } from '@sosed/i18n';

/** Шапка: плашка 24 × 24 с радиусом 7, «С» Unbounded 600 13 px и «Соседи» Unbounded 600 16 px.
 *  Классы — только уже собранные, нестандартное — стилем элемента: CSS у приложения один и входит в
 *  бюджет первого экрана, а этот код — в чанке оболочки. */
export function BrandMark() {
  const { t } = useTranslation();
  const name = t('app.name');
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className="flex size-6 shrink-0 items-center justify-center bg-accent font-display text-cap font-semibold text-accent-ink"
        style={{ borderRadius: 7 }}
      >
        {name.charAt(0)}
      </span>
      <span className="font-display text-title text-text">{name}</span>
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
