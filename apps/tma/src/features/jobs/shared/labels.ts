// Подписи заявки в ленте S13 и на экране заявки S15 (DEVELOPMENT_PLAN 5.3): «когда» бейджем,
// бюджет, «Лиман, ≈ 1,2 км», счётчик мест и «в «Соседях» 3 месяца». Время — по Белграду, как у
// сервера и мастера S20b: «Сегодня 18–21» — только в тот же день, иначе дата.
import type { JobCardOut, MoneyOut } from '@sosed/api-client';
import type { BudgetUnit, JobUrgency } from '@sosed/domain';
import { budgetAsPrice, businessDay, responseSlots } from '@sosed/domain';
import { useFormat, useTranslation } from '@sosed/i18n';
import type { JobCardBadge, JobSlots } from '@sosed/ui-web';

interface JobWhen {
  urgency: JobUrgency;
  preferred_from: string | null;
  preferred_to: string | null;
}

interface JobBudget {
  budget_type: JobCardOut['budget_type'];
  budget_min: MoneyOut | null;
  budget_max: MoneyOut | null;
  budget_unit: BudgetUnit;
}

const MONTHS_IN_YEAR = 12;

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Бейдж «когда»: «Срочно», «Сегодня 18–21» (на S15 — «18:00–21:00»), «На неделе», «Завтра в
 *  10:00». `full` — время с минутами, как на экране заявки. */
export function useWhenBadge(): (job: JobWhen, full?: boolean) => JobCardBadge {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  return (job, full = false) => {
    if (job.urgency === 'asap')
      return { label: common('urgency.asap'), tone: 'urgent', icon: 'zap' };
    const from = job.preferred_from ? new Date(job.preferred_from) : null;
    const to = job.preferred_to ? new Date(job.preferred_to) : null;
    const now = new Date();
    if (from && to && job.urgency === 'today' && businessDay(from) === businessDay(now)) {
      const hour = (date: Date) => {
        const time = format.time(date);
        return full ? time : time.replace(/:00$/, '');
      };
      return {
        label: t('card.todaySlot', { from: hour(from), to: hour(to) }),
        tone: 'info',
        icon: 'clock',
      };
    }
    if (from)
      return { label: capitalized(format.calendar(from, now)), tone: 'info', icon: 'clock' };
    if (job.urgency === 'today') {
      return { label: common('urgency.today'), tone: 'info', icon: 'clock' };
    }
    return { label: common(`urgency.${job.urgency}`), tone: 'info' };
  };
}

/** Бюджет: «5 000 RSD», «4 000–6 000 RSD», «1 500 RSD/час»; договорная — `null`. `unit: false`
 *  — без единицы: на S15 она отдельной подписью. */
export function useBudgetText(): (job: JobBudget, options?: { unit?: boolean }) => string | null {
  const format = useFormat();
  return (job, { unit = true } = {}) => {
    if (job.budget_type === 'negotiable') return null;
    const price = budgetAsPrice({
      type: job.budget_type,
      min: job.budget_min?.amount ?? null,
      max: job.budget_max?.amount ?? null,
      unit: job.budget_unit,
    });
    return format.price(unit ? price : { ...price, unit: null });
  };
}

/** «Лиман, ≈ 1,2 км»: район из справочника и расстояние, если известна точка. */
export function usePlaceText(): (district: string | null, distanceM: number | null) => string {
  const format = useFormat();
  return (district, distanceM) =>
    [district, distanceM !== null ? format.distance(distanceM) : null].filter(Boolean).join(', ');
}

/** Полоски мест и «откликов 3 из 5». */
export function useSlots(): (job: { max_responses: number; responses_count: number }) => JobSlots {
  const { t: common } = useTranslation();
  return (job) => {
    const slots = responseSlots({
      maxResponses: job.max_responses,
      responsesCount: job.responses_count,
    });
    return {
      taken: slots.taken,
      total: slots.total,
      label: common('count.responsesOf', { count: slots.taken, total: slots.total }),
    };
  };
}

/** Полных месяцев между датами — для «в «Соседях» 3 месяца». */
export function monthsBetween(since: Date, now: Date): number {
  const months =
    (now.getUTCFullYear() - since.getUTCFullYear()) * MONTHS_IN_YEAR +
    (now.getUTCMonth() - since.getUTCMonth());
  return Math.max(0, now.getUTCDate() < since.getUTCDate() ? months - 1 : months);
}

/** «В «Соседях» 3 месяца», «… 2 года», «… меньше месяца». */
export function useMemberFor(): (since: string) => string {
  const { t } = useTranslation('jobs');
  return (since) => {
    const months = monthsBetween(new Date(since), new Date());
    if (months < 1) return t('job.client.memberNew');
    if (months < MONTHS_IN_YEAR) return t('job.client.memberMonths', { count: months });
    return t('job.client.memberYears', { count: Math.floor(months / MONTHS_IN_YEAR) });
  };
}
