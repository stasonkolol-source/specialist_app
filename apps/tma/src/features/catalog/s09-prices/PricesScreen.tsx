// S09 Прайс специалиста (DEVELOPMENT_PLAN 4.5): все видимые позиции по группам — категориям в
// порядке прайса, без группы — в конце «Другое». Под названием — длительность («до 1 часа») и
// описание; справа — сумма и под ней единица («за визит»). Памятка: цены ориентировочные. Имя и
// фото — из профиля S08 (обычно уже в кэше). Строка — «Заказать эту услугу»: мастер заявки S20a с
// её категорией и названием, прямым запросом этому специалисту (5.6).
import type { CardServiceOut, CardServicesOut, SpecialistProfileOut } from '@sosed/api-client';
import { isUnavailable, priceGroups, useSpecialistCard, useSpecialistServices } from '@sosed/hooks';
import { useLocale, useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Banner,
  EmptyState,
  Group,
  Heading,
  Row,
  RowsSkeleton,
  SectionTitle,
  Skeleton,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useId } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { Unavailable } from '../shared/Unavailable.tsx';
import { avatarSrc, serviceDuration } from '../shared/card.ts';
import { CARD_PATHS, CREATE_JOB_PATH } from '../shared/paths.ts';
import { PriceColumn } from './PriceColumn.tsx';

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

  if ([card, services].some((load) => isUnavailable(load.error))) return <Unavailable />;
  if (card.data && services.data) return <Prices card={card.data} services={services.data} />;
  const failed = [card, services].find((load) => load.isError);
  if (failed) {
    return (
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
  return <Loading card={card.data} />;
}

/** Прайс ещё грузится: шапка — из профиля S08 в кэше (его обычно открыли перед этим), позиции —
 *  скелетоном строк. */
function Loading({ card }: { card: SpecialistProfileOut | undefined }) {
  const { t } = useTranslation('catalog');
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6" aria-busy="true">
      <div className="flex items-center gap-3">
        {card ? (
          <Avatar
            name={card.display_name}
            size="sm"
            src={avatarSrc(card.avatar, AVATAR_SM)}
            placeholder={card.avatar?.placeholder}
          />
        ) : (
          <Skeleton round screen className="size-9 shrink-0" />
        )}
        <div className="flex min-w-0 grow flex-col">
          <Heading variant="h2" as="h1">
            {t('prices.title')}
          </Heading>
          <SkeletonText size="cap" screen className="w-1/2" />
        </div>
      </div>
      <Banner tone="info">{t('prices.note')}</Banner>
      <SkeletonText size="cap" screen className="w-1/4" />
      <RowsSkeleton rows={4} leading="none" trailing />
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
            profileId={card.id}
          />
        ))
      )}
    </section>
  );
}

/** Услуга ведёт в мастер заявки S20a с её категорией и названием (5.2) — прямым запросом этому
 *  специалисту (5.6): заявку увидит только этот специалист. */
function PriceSection({
  title,
  items,
  profileId,
}: {
  title: string;
  items: CardServiceOut[];
  profileId: string;
}) {
  const id = useId();
  const router = useRouter();
  const order = (service: CardServiceOut) => ({
    to: CREATE_JOB_PATH,
    search: {
      category: service.category_id ?? undefined,
      title: service.title,
      direct: profileId,
    },
  });
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <SectionTitle id={id}>{title}</SectionTitle>
      <Group>
        {items.map((service) => (
          <Row
            key={service.id}
            title={service.title}
            subtitle={<ServiceNote service={service} />}
            trailing={<PriceColumn service={service} />}
            href={router.history.createHref(router.buildLocation(order(service)).href)}
            onClick={(event) => {
              event.preventDefault();
              void router.navigate(order(service));
            }}
          />
        ))}
      </Group>
    </section>
  );
}

/** Длительность («до 1 часа») и описание позиции под названием; единица — в колонке цены. Ни
 *  того, ни другого — строка в одну линию. */
function ServiceNote({ service }: { service: CardServiceOut }) {
  const { t } = useTranslation('catalog');
  const duration = serviceDuration(service);
  if (duration === null && !service.description) return null;
  return (
    <>
      {duration !== null && <span className="block">{t(`prices.durations.${duration}`)}</span>}
      {service.description && (
        <span className="line-clamp-2 block whitespace-pre-line">{service.description}</span>
      )}
    </>
  );
}
