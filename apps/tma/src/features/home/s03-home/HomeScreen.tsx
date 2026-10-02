// S03 Главная: каркас маршрута (0.21a); экран по макету design/project — в шаге 4.8. До него
// «Услуги» — вход в каталог (4.4): строка поиска ведёт в выдачу S05, «Все услуги» — в S04.
// Переключатель «Услуги / Вещи» виден по флагу goods.segment (client-config, ADR-0019):
// «Вещи» в MVP — заглушка S58.
import { FLAGS, useFlag } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { EmptyState, Group, Heading, Row, SearchField, Segmented } from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { FormEvent } from 'react';
import { useState } from 'react';

/** Каталог S04 и выдача S05 (features/catalog): фичи не импортируют друг друга. */
const CATALOG_PATH = '/catalog';
const RESULTS_PATH = '/catalog/results';

type Segment = 'services' | 'goods';

export function HomeScreen() {
  const { t } = useTranslation();
  const catalog = useTranslation('catalog').t;
  const router = useRouter();
  const goodsSegment = useFlag(FLAGS.goodsSegment);
  const [segment, setSegment] = useState<Segment>('services');
  const [query, setQuery] = useState('');
  const showGoods = goodsSegment && segment === 'goods';
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const q = query.trim();
    if (q) void router.navigate({ to: RESULTS_PATH, search: { q } });
  };
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
        <EmptyState as="h2" icon="bag" title={t('goods.soonTitle')}>
          {t('goods.soonText')}
        </EmptyState>
      ) : (
        <>
          <form onSubmit={submit}>
            <SearchField
              label={catalog('results.search')}
              placeholder={catalog('results.search')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </form>
          <Group>
            <Row
              icon="grid"
              title={catalog('categories.title')}
              chevron
              href={router.history.createHref(CATALOG_PATH)}
              onClick={(event) => {
                event.preventDefault();
                void router.navigate({ to: CATALOG_PATH });
              }}
            />
          </Group>
        </>
      )}
    </section>
  );
}
