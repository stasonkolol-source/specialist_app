// S09 Прайс специалиста (DEVELOPMENT_PLAN 4.5): все видимые позиции по группам — категориям в
// порядке прайса, без группы — в конце «Другое». Под названием — длительность и единица («до 1
// часа · за визит») и описание; справа — сумма. Памятка: цены ориентировочные. Имя и фото — из
// профиля S08 (обычно уже в кэше). «Заказать эту услугу» — с шагом 5.2, до того строки не ссылки.
import type { CardServiceOut, CardServicesOut, SpecialistProfileOut } from '@sosed/api-client';
import { isUnavailable, priceGroups, useSpecialistCard, useSpecialistServices } from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Banner,
  EmptyState,
  Group,
  Heading,
  Price,
  Row,
  SectionTitle,
  Skeleton,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useId } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import { avatarSrc, priceAmount, serviceDuration, serviceUnit } from '../shared/card.ts';
import { CARD_PATHS } from '../shared/paths.ts';

/** Аватар sm — 36 px. */
const AVATAR_SM = 36;

export function PricesScreen() {
  const { profileId } = useParams({ strict: false }) as { profileId: string };
  const router = useRouter();
  const locale = useLocale();
  const card = useSpecialistCard(profileId, locale);
  const services = useSpecialistServices(profileId, locale);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CARD_PATHS.profile, params: { profileId }, replace: true });
  });

  if (card.data && services.data) return <Prices card={card.data} services={services.data} />;
  const failed = [card, services].find((load) => load.isError);
  if (failed) {
    return isUnavailable(failed.error) ? (
      <Unavailable />
    ) : (
      <section className="flex flex-col px-4 pt-3 pb-6">
        <LoadError
          error={failed.error}
          onRetry={() => {
            for (const load of [card, services]) if (load.isError) void load.refetch();
          }}
          retrying={card.isRefetching || services.isRefetching}
        />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6" aria-busy="true">
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-52 w-full" />
    </section>
  );
}

function Prices({ card, services }: { card: SpecialistProfileOut; services: CardServicesOut }) {
  const { t } = useTranslation('catalog');
  const groups = priceGroups(services);
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <div className="flex items-center gap-3">
        <Avatar
          name={card.display_name}
          size="sm"
          src={avatarSrc(card.avatar, AVATAR_SM)}
          placeholder={card.avatar?.placeholder}
        />
        <div className="flex min-w-0 grow flex-col">
          <Heading variant="h2" as="h1">
            {t('prices.title')}
          </Heading>
          <Text variant="cap">
            {t('prices.summary', { name: card.display_name, count: services.items.length })}
          </Text>
        </div>
      </div>
      <Banner tone="info">{t('prices.note')}</Banner>
      {groups.length === 0 ? (
        <EmptyState as="h2" icon="list" title={t('prices.empty')} />
      ) : (
        groups.map((group) => (
          <PriceSection
            key={group.category?.id ?? 'other'}
            title={group.category?.name ?? t('prices.other')}
            items={group.items}
          />
        ))
      )}
    </section>
  );
}

function PriceSection({ title, items }: { title: string; items: CardServiceOut[] }) {
  const id = useId();
  const format = useFormat();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <SectionTitle id={id}>{title}</SectionTitle>
      <Group>
        {items.map((service) => (
          <Row
            key={service.id}
            title={service.title}
            subtitle={<ServiceNote service={service} />}
            trailing={<Price>{priceAmount(format, service)}</Price>}
          />
        ))}
      </Group>
    </section>
  );
}

/** «до 1 часа · за визит» и описание позиции под ним. */
function ServiceNote({ service }: { service: CardServiceOut }) {
  const { t } = useTranslation('catalog');
  const common = useTranslation().t;
  const duration = serviceDuration(service);
  const unit = serviceUnit(service);
  const note = [
    duration === null ? null : t(`prices.durations.${duration}`),
    unit === null ? null : common(`unit.${unit}`),
  ]
    .filter(Boolean)
    .join(' · ');
  if (!note && !service.description) return null;
  return (
    <>
      {note && <span className="block">{note}</span>}
      {service.description && (
        <span className="line-clamp-2 block whitespace-pre-line">{service.description}</span>
      )}
    </>
  );
}
