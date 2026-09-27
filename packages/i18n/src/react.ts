// React-обвязка: фичи берут переводы и форматтеры отсюда, а не из react-i18next напрямую.
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { Format } from './format.ts';
import { createFormat } from './format.ts';
import { currentLocale } from './instance.ts';
import type { Locale } from './locale.ts';

export { I18nextProvider, Trans, useTranslation } from 'react-i18next';

export function useLocale(): Locale {
  const { i18n } = useTranslation();
  return currentLocale(i18n);
}

export function useFormat(): Format {
  const locale = useLocale();
  return useMemo(() => createFormat(locale), [locale]);
}
