// Сумма бюджета в поле S20c: только цифры, не больше девяти, тысячи — через неразрывный пробел.
import { BUDGET_DIGITS } from '@sosed/hooks';
import { NBSP } from '@sosed/i18n';

/** «5000» → «5 000»; ведущие нули и не-цифры — прочь. */
export function groupDigits(raw: string): string {
  const digits = raw.replace(/\D/g, '').replace(/^0+/, '').slice(0, BUDGET_DIGITS);
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}
