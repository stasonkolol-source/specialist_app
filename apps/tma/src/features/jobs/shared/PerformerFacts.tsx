// Факты об исполнителе в карточке отклика S23 и мини-профиле S24 (сигналы доверия для беты):
// клиент выбирает незнакомого мастера при нуле отзывов, поэтому под рейтингом — только счётчики
// и даты, не оценки (ADR-0016; ZZP 35/2026 ст. 19–20): «В «Соседях» 3 месяца», «Сделок: 4»,
// «Работ в портфолио: 12», «Отзывов до платформы: 3», «Обычно отвечает за 15 мин»; нули и
// неизвестное не пишем. Бейджи — не больше двух, по важности: «Телефон подтверждён», «Проверен
// модератором», «Откликнулся первым», «Приглашён командой», «Новый аккаунт» (тихий тон: уровень
// доверия 0 — факт об аккаунте, профиль-то проверен). «Подработка» и «Без профиля» — в строке
// рейтинга рядом с районом: это вид исполнителя, а не бейдж.
import type { ResponseCardOut, ResponsePerformerCardOut } from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { Badge } from '@sosed/ui-web';
import type { SpecialistBadge } from '@sosed/ui-web';

import { useMemberFor } from './labels.ts';

const MAX_BADGES = 2;
const MINUTES_IN_HOUR = 60;
const PRO = 'pro';

type Translate = ReturnType<typeof useTranslation<'jobs'>>['t'];

/** «Подработка» у профиля подработки, «Без профиля» у отклика без профиля; у специалиста — нет. */
export function performerKind(
  performer: Pick<ResponsePerformerCardOut, 'profile_id' | 'kind'>,
  t: Translate,
): string | null {
  if (performer.profile_id === null) return t('manage.noProfile');
  return performer.kind === PRO ? null : t('manage.casual');
}

/** Бейджи карточки отклика по важности, не больше двух. */
export function performerBadges(
  card: Pick<ResponseCardOut, 'is_first'> & {
    performer: Pick<
      ResponsePerformerCardOut,
      'phone_verified' | 'profile_checked_at' | 'is_founding' | 'is_new_account'
    >;
  },
  t: Translate,
): SpecialistBadge[] {
  const { performer } = card;
  const badges: SpecialistBadge[] = [];
  if (performer.phone_verified)
    badges.push({ label: t('manage.phone'), tone: 'info', icon: 'shield' });
  if (performer.profile_checked_at !== null) {
    badges.push({ label: t('manage.moderated'), tone: 'info', icon: 'check' });
  }
  if (card.is_first) badges.push({ label: t('manage.first'), tone: 'ok' });
  if (performer.is_founding)
    badges.push({ label: t('manage.founding'), tone: 'info', icon: 'users' });
  if (performer.is_new_account) badges.push({ label: t('manage.newAccount'), tone: 'mute' });
  return badges.slice(0, MAX_BADGES);
}

export function PerformerBadges({ card }: { card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const badges = performerBadges(card, t);
  if (badges.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {badges.map((badge) => (
        <Badge key={badge.label} tone={badge.tone} icon={badge.icon}>
          {badge.label}
        </Badge>
      ))}
    </div>
  );
}

/** Строка фактов под рейтингом: стаж в «Соседях», сделки, работы, отзывы до платформы, время
 *  ответа — через «·»; нечего сказать — строки нет. */
export function PerformerFacts({ performer }: { performer: ResponsePerformerCardOut }) {
  const { t } = useTranslation('jobs');
  const memberFor = useMemberFor();
  const facts = [
    performer.member_since ? memberFor(performer.member_since) : null,
    performer.completed_deals > 0 ? t('manage.deals', { count: performer.completed_deals }) : null,
    performer.works_count > 0 ? t('manage.works', { count: performer.works_count }) : null,
    performer.pre_platform_count > 0
      ? t('manage.prePlatform', { count: performer.pre_platform_count })
      : null,
    responseTime(performer.response_time_minutes, t),
  ].filter((fact): fact is string => fact !== null);
  if (facts.length === 0) return null;
  return <p className="m-0 text-cap text-text2">{facts.join(' · ')}</p>;
}

/** «Обычно отвечает за 15 мин»; от часа — часами, как на S08, но короче: строка и так длинная. */
function responseTime(minutes: number | null, t: Translate): string | null {
  if (minutes === null) return null;
  if (minutes < MINUTES_IN_HOUR) return t('manage.responseMinutes', { count: minutes });
  return t('manage.responseHours', { count: Math.round(minutes / MINUTES_IN_HOUR) });
}
