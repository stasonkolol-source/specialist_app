// Доступ к файлам @fontsource из node (генерация и тесты).
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

/** Путь к файлу пакета по спецификатору вида `@fontsource/onest/files/x.woff2`. */
export function resolveFontFile(spec: string): string {
  return require.resolve(spec);
}

export function readFontCss(pkg: string, weight: number): string {
  return readFileSync(resolveFontFile(`${pkg}/${weight}.css`), 'utf8');
}
