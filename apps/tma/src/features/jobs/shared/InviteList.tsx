// «Пригласите специалистов» (DEVELOPMENT_PLAN 5.6): подходящие по категории и городу заявки из
// каталога — фото, имя, рейтинг или «Новый специалист», район; «Пригласить» — им уведомление с
// «Откликнуться шаблоном», приглашённым — «Приглашён». Своя опубликованная заявка: S21 — три
// первых, как на артборде (экран результата не перегружен), шторка S23 — все подходящие.
import type { JobOut, SpecialistCardOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import {
  resultItems,
  useInviteSpecialists,
  useJobInvites,
  useSpecialistSearch,
} from '@sosed/hooks';
import { useFormat, useLocale, useTranslation } from '@sosed/i18n';
import { Avatar, Badge, Banner, Button, Group, Row, Skeleton, Text } from '@sosed/ui-web';

import { performerPlace, useWholeCity } from './labels.ts';

/** Сколько подходящих показать: больше десяти в заявку не пригласить. */
const SUGGESTIONS = 10;

export function InviteList({ job, shown = SUGGESTIONS }: { job: JobOut; shown?: number }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const wholeCity = useWholeCity(job.city_id);
  const locale = useLocale();
  const search = useSpecialistSearch(locale, {
    city_id: job.city_id,
    category_id: job.category_id,
  });
  const invites = useJobInvites(job.id);
  const invite = useInviteSpecialists();
  const invited = new Set(invites.data?.items.map((item) => item.profile_id) ?? []);
  const found = resultItems(search.data).slice(0, shown);
  const limit = invites.data?.limit ?? SUGGESTIONS;
  const full = invited.size >= limit;
  const failure = invite.error;
  const detail =
    failure instanceof ApiError && failure.status < 500 ? failure.problem.detail : null;
  const subtitle = (card: SpecialistCardOut) =>
    [
      card.rating !== null ? format.rating(card.rating) : common('rating.new'),
      performerPlace(card, wholeCity),
    ]
      .filter(Boolean)
      .join(' · ');
  return (
    <>
      {invite.isError && (
        <Banner tone="danger" role="alert">
          {detail ?? t('manage.error')}
        </Banner>
      )}
      {invited.size > 0 && (
        <Text variant="cap">{t('manage.inviteLimit', { count: invited.size, limit })}</Text>
      )}
      {!search.data ? (
        <Skeleton radius="card" className="h-40 w-full" />
      ) : found.length === 0 ? (
        <Text secondary>{t('manage.inviteNobody')}</Text>
      ) : (
        <Group>
          {found.map((card) => (
            <Row
              key={card.profile_id}
              leading={
                <Avatar
                  name={card.display_name}
                  size="sm"
                  src={card.avatar?.url}
                  placeholder={card.avatar?.placeholder}
                />
              }
              title={card.display_name}
              subtitle={subtitle(card)}
              trailing={
                invited.has(card.profile_id) ? (
                  <Badge tone="ok">{t('manage.invited')}</Badge>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={full || invite.isPending}
                    onClick={() => invite.mutate({ jobId: job.id, profileIds: [card.profile_id] })}
                  >
                    {t('manage.invite')}
                  </Button>
                )
              }
            />
          ))}
        </Group>
      )}
    </>
  );
}
