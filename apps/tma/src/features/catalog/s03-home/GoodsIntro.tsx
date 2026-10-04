// Шапка S58 «Вещи — скоро» (7.5): в чанке Главной — она же ждёт чанк экрана (GoodsSoon.tsx) и
// заменяет его, если он не скачался: сегмент не пустеет и не роняет Главную. По артборду —
// заголовок раздела (.h1, Unbounded) под значком 72 px, а не заголовок пустого состояния.
import { useTranslation } from '@sosed/i18n';
import { Heading, Icon, Text } from '@sosed/ui-web';

export function GoodsIntro() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col items-center gap-2 px-2 pt-2 text-center">
      <span
        aria-hidden="true"
        className="flex size-18 items-center justify-center rounded-full bg-accent-soft text-accent-soft-ink"
      >
        <Icon name="bag" size={32} />
      </span>
      <Heading variant="h1">{t('goods.soonTitle')}</Heading>
      <Text secondary>{t('goods.soonText')}</Text>
    </section>
  );
}
