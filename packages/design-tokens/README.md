# @sosed/design-tokens

Токены из утверждённого `design/ui.css` (источник правды — макет, эталон не правим).

| Экспорт                           | Что это                                                                                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@sosed/design-tokens/tokens.css` | CSS-переменные с именами из `ui.css`: `:root` — светлая тема, `[data-theme='dark']` — тёмная                                                                        |
| `@sosed/design-tokens/theme.css`  | Блок `@theme inline` для Tailwind 4: `bg-surface`, `text-text2`, `rounded-card`, `text-h1`, `font-display`… Палитра, радиусы и шкала Tailwind по умолчанию сброшены |
| `@sosed/design-tokens/fonts.css`  | `@font-face` Onest 400–700 и Unbounded 500/600 из `@fontsource`, woff2, `font-display: swap`                                                                        |
| `@sosed/design-tokens`            | `tokens` — TS-объект для этапа 2 (React Native)                                                                                                                     |

Правка токенов: `tokens.json` → `pnpm -F design-tokens generate` → коммит вместе с `src/*.generated.*`.
Тесты сверяют токены с `ui.css` (темы, аватары, радиусы, типошкала, размеры), актуальность сгенерированных
файлов, контраст пар (`pnpm -F design-tokens check:contrast`) и наличие глифов č ć đ š ž и кириллицы в самих woff2.

Отличия от `ui.css` — только добавления (`additions` в `tokens.json`):

- `danger-ink` — текст на `--danger`. В `ui.css` у `.mbtn.dng` жёстко `#fff`, в тёмной теме это 2,3:1; тёмное значение `#2B0A0A` даёт 7,2:1.
- `toast`, `toast-ink`, `av1…av5`, размеры шрифта аватаров и радиусы компонентов (`panel` — 14 px: баннер, поиск, опция, тост) — значения из классов `ui.css`, вынесенные в токены, чтобы в компонентах не было hex.
- У Onest кроме четырёх подмножеств подключено `math`: в текстах макетов есть «≈» и «→». Браузер качает его, только если символ есть на экране.

Preload первого экрана — `FONT_PRELOAD` (Unbounded 600 и Onest 400, 600 — кириллица, Onest 400 — латиница); ссылки ставит плагин `fontPreload()` (`@sosed/design-tokens/vite`) после скрипта и стилей.
