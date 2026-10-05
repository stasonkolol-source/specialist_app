/** Склейка классов без пустых значений. */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/** Класс цвета текста из токенов темы (theme.css, --color-*): text-danger, text-accent… Размеры
 *  шрифта (text-cap, text-sm…) сюда не попадают. Варианты (hover:, dark:) — не свой цвет. */
const TEXT_COLOUR =
  /^text-(?:bg2?|surface|text2?|line|field|accent(?:-ink|-soft(?:-ink)?)?|urgent(?:-ink|-soft(?:-ink)?)?|info-(?:soft|ink)|danger(?:-ink|-soft)?|star|scrim|seg-(?:track|on)|toast(?:-ink)?|knob|av[1-5](?:-ink)?)$/;

/** Цвет компонента по умолчанию (серый подписи) — только если вызывающий не задал свой. Оба класса
 *  разом не годятся: у них одна специфичность, и побеждает тот, что позже в собранном CSS, —
 *  .text-text2 идёт после .text-danger, и ошибка оставалась серой (SMOKE-8). */
export function colourOr(fallback: string, className: string | undefined): string | false {
  return !className?.split(/\s+/).some((name) => TEXT_COLOUR.test(name)) && fallback;
}

/** Видимый фокус с клавиатуры для всех интерактивных элементов. */
export const FOCUS =
  'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';
