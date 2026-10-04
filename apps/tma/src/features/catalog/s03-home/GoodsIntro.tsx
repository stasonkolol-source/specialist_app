// Шапка S58 «Вещи — скоро» (7.5): в чанке Главной — она же ждёт чанк экрана (GoodsSoon.tsx) и
// заменяет его, если он не скачался: сегмент не пустеет и не роняет Главную.
import { useTranslation } from '@sosed/i18n';
import { EmptyState } from '@sosed/ui-web';

export function GoodsIntro() {
  const { t } = useTranslation();
  return (
    <EmptyState as="h1" icon="bag" title={t('goods.soonTitle')} className="px-2 pt-2">
      {t('goods.soonText')}
    </EmptyState>
  );
}
