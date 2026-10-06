// Шрифты сербской латиницы (č, ć, š, ž, đ — подмножество latin-ext). Ссылки preload в index.html
// (FONT_PRELOAD, design-tokens) их не берут: язык там ещё неизвестен, а русскому первому экрану они не
// нужны. Для sr-Latn те же начертания первого экрана просим загрузить, как только язык известен, а не
// когда раскладка экрана их найдёт: заголовок не перестраивается, когда шрифт приходит позже текста.
import type { Locale } from '@sosed/i18n';

/** Начертания первого экрана — те же, что в FONT_PRELOAD. */
const FIRST_SCREEN_FACES = ['600 1em Unbounded', '400 1em Onest', '500 1em Onest', '600 1em Onest'];
/** По этим буквам браузер выбирает файлы latin-ext (unicode-range) и только их. */
const SERBIAN_LATIN = 'čćšžđČĆŠŽĐ';

export function preloadLocaleFonts(locale: Locale): void {
  if (locale !== 'sr-Latn' || !('fonts' in document)) return;
  for (const face of FIRST_SCREEN_FACES) {
    document.fonts.load(face, SERBIAN_LATIN).catch(() => undefined);
  }
}
