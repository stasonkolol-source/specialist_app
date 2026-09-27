// S03 Главная: каркас маршрута (0.21a); экран по макету design/project — в шаге этапа 1.
// Переключатель «Услуги / Вещи» виден по флагу goods.segment (client-config, ADR-0019):
// «Вещи» в MVP — заглушка S58.
import { FLAGS, useFlag } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { EmptyState, Heading, Segmented } from '@sosed/ui-web';
import { useState } from 'react';

type Segment = 'services' | 'goods';

export function HomeScreen() {
  const { t } = useTranslation();
  const goodsSegment = useFlag(FLAGS.goodsSegment);
  const [segment, setSegment] = useState<Segment>('services');
  const showGoods = goodsSegment && segment === 'goods';
  return (
    <section className="flex flex-col gap-3 px-4 pt-4">
      <Heading variant="h1">{t('nav.home')}</Heading>
      {goodsSegment && (
        <Segmented<Segment>
          label={t('home.segment')}
          value={segment}
          onChange={setSegment}
          options={[
            { value: 'services', label: t('home.services') },
            { value: 'goods', label: t('home.goods') },
          ]}
        />
      )}
      {showGoods ? (
        <EmptyState icon="bag" title={t('goods.soonTitle')}>
          {t('goods.soonText')}
        </EmptyState>
      ) : (
        <EmptyState icon="home" title={t('stub.title')}>
          {t('stub.text')}
        </EmptyState>
      )}
    </section>
  );
}
