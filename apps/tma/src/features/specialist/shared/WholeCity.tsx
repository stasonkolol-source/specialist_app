// Переключатель «Весь Нови-Сад» (wholeCity.ts): карточка-галочка во всю ширину над районами —
// нажимается вся строка, а подпись объясняет, что значит «весь».
import { useTranslation } from '@sosed/i18n';
import { Option } from '@sosed/ui-web';

export function WholeCity({
  city,
  checked,
  onChange,
}: {
  /** Название города; не загрузилось — «Весь город». */
  city: string | null;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const { t } = useTranslation('specialist');
  return (
    <Option
      kind="checkbox"
      title={city ? t('become.area.wholeCity', { city }) : t('become.area.wholeCityPlain')}
      description={t('become.area.wholeCityHint')}
      checked={checked}
      onChange={onChange}
    />
  );
}
