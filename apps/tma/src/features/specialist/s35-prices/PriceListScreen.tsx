// S35 Прайс-лист (DEVELOPMENT_PLAN 2.11): позиции по группам — категориям профиля, у каждой — тип
// цены и длительность, «Скрыта» у выключенной. Нажатие — правка S36; «…» — «Выше», «Ниже»,
// «Скрыть»/«Показать» в нативном попапе Telegram; MainButton — новая позиция. Перетаскивание с
// артборда заменено кнопками «Выше / Ниже»: в WebView Telegram жест спорит со свайпом закрытия.
// Ориентиры рынка — v1.
import type { CategoryOut, ProfileOut, ServiceOut, ServicesOut } from '@sosed/api-client';
import {
  getPricingListMyServicesQueryKey,
  pricingChangeMyService,
  pricingReorderMyServices,
} from '@sosed/api-client';
import {
  groupServices,
  moveService,
  myProfileQueryKey,
  useCategories,
  useMyProfile,
  useMyServices,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  Badge,
  Banner,
  EmptyState,
  Group,
  Heading,
  IconButton,
  Price,
  SectionTitle,
  Text,
} from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect, useId } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';
import { DURATIONS, MAX_PRICE_ITEMS, categoryNames, priceAmount } from '../shared/prices.ts';

export function PriceListScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  const services = useMyServices({ enabled: Boolean(profile.data) });
  const categories = useCategories(useLocale());
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.home, replace: true });
  });
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data && services.data && categories.data) {
    return (
      <PriceList profile={profile.data} services={services.data.items} tree={categories.data} />
    );
  }
  const loads = [profile, services, categories];
  const failed = loads.find((load) => load.isError);
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Heading variant="h2" as="h1">
        {t('prices.title')}
      </Heading>
      <LoadState
        shape="prices"
        error={failed ? failed.error : null}
        onRetry={() => {
          for (const load of loads) if (load.isError) void load.refetch();
        }}
        retrying={loads.some((load) => load.isFetching)}
      />
    </section>
  );
}

function PriceList({
  profile,
  services,
  tree,
}: {
  profile: ProfileOut;
  services: ServiceOut[];
  tree: CategoryOut[];
}) {
  const { t } = useTranslation('specialist');
  const { t: common } = useTranslation();
  const format = useFormat();
  const router = useRouter();
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const groupsId = useId();
  const names = categoryNames(tree);
  const groups = groupServices(services, profile.category_ids);
  const full = services.length >= MAX_PRICE_ITEMS;

  useStepButton({
    text: t('prices.add'),
    onClick: () => void router.navigate({ to: CABINET_PATHS.newPrice }),
    visible: !full,
  });

  // правка списка: ответ — новый прайс; полнота профиля зависит от прайса — её перечитываем
  const update = useMutation({
    mutationFn: async ({ service, action }: { service: ServiceOut; action: string }) => {
      if (action === 'up' || action === 'down') {
        const order = moveService(services, service.id, action === 'up' ? -1 : 1);
        return order ? (await pricingReorderMyServices({ service_ids: order })).items : services;
      }
      const changed = await pricingChangeMyService(service.id, { is_active: !service.is_active });
      return services.map((item) => (item.id === changed.id ? changed : item));
    },
    onSuccess: (items) => {
      queryClient.setQueryData<ServicesOut>(getPricingListMyServicesQueryKey(), { items });
      void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
    },
  });

  const actions = async (service: ServiceOut) => {
    const choice = await platform.popup({
      message: service.title,
      buttons: [
        ...(moveService(services, service.id, -1) ? [{ id: 'up', text: t('prices.up') }] : []),
        ...(moveService(services, service.id, 1) ? [{ id: 'down', text: t('prices.down') }] : []),
        { id: 'toggle', text: t(service.is_active ? 'prices.hide' : 'prices.show') },
      ],
    });
    if (choice === 'up' || choice === 'down' || choice === 'toggle') {
      update.mutate({ service, action: choice });
    }
  };
  const open = (service: ServiceOut) => (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: CABINET_PATHS.price, params: { serviceId: service.id } });
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {t('prices.title')}
        </Heading>
        {services.length > 0 && (
          <Text variant="cap">{t('prices.count', { count: services.length })}</Text>
        )}
      </div>
      {services.length === 0 && (
        <EmptyState as="h2" size="h3" icon="list" title={t('prices.title')}>
          {t('prices.empty')}
        </EmptyState>
      )}
      {groups.map((group, index) => {
        const titleId = `${groupsId}-${index}`;
        const title =
          group.categoryId === null
            ? t('prices.noGroup')
            : (names.get(group.categoryId) ?? t('prices.noGroup'));
        return (
          <section
            key={group.categoryId ?? 'none'}
            aria-labelledby={titleId}
            className="flex flex-col gap-2"
          >
            <SectionTitle id={titleId}>{title}</SectionTitle>
            <Group>
              {group.items.map((service) => (
                <div
                  key={service.id}
                  className="flex items-center gap-2 border-b border-line py-2 pr-1 pl-4 last:border-b-0"
                >
                  <a
                    href={router.history.createHref(`${CABINET_PATHS.prices}/${service.id}`)}
                    onClick={open(service)}
                    className="flex min-w-0 flex-1 flex-col text-text outline-none focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    <span className="text-body">{service.title}</span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Text as="span" variant="cap">
                        <ServiceKind service={service} />
                      </Text>
                      {!service.is_active && <Badge>{t('prices.hidden')}</Badge>}
                    </span>
                  </a>
                  <Price>{priceAmount(format, service, common('price.negotiable'))}</Price>
                  <IconButton
                    icon="more"
                    plain
                    label={t('prices.actions', { title: service.title })}
                    onClick={() => void actions(service)}
                    disabled={update.isPending}
                  />
                </div>
              ))}
            </Group>
          </section>
        );
      })}
      {full && <Banner tone="info">{t('prices.full', { max: MAX_PRICE_ITEMS })}</Banner>}
      {update.isError && <SaveError error={update.error} />}
    </section>
  );
}

/** Подпись под названием: тип цены и длительность — «от · 1–2 часа». */
function ServiceKind({ service }: { service: ServiceOut }) {
  const { t } = useTranslation('specialist');
  const duration = DURATIONS.find((minutes) => minutes === service.duration_min);
  const kind = t(`prices.type.${service.price_type}`);
  return <>{duration ? `${kind} · ${t(`price.durations.${duration}`)}` : kind}</>;
}
