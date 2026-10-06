// S33 Кабинет специалиста (DEVELOPMENT_PLAN 2.10): статус профиля, полнота с первой подсказкой,
// «Доступен сегодня до …» (переключатель: включает «до 20:00» или ближайший вариант, подробно — S38),
// у опубликованного профиля — «Посмотреть как клиент» (публичный профиль S08), и переходы к правке
// S34, прайсу S35, портфолио S37, доступности S38 и «Отзывам до платформы» S55 (7.6а, «2 из 5» —
// занятые места). Черновик и «нужны правки» продолжают мастер S32 с нужного шага (MainButton);
// причина отказа — прямо в строке статуса. Сюда же ведёт «Отправить на проверку» (UX №7): срок,
// «бот напишет» и одно действие на время ожидания — «Добавить фото работ» (S37). Опубликованному,
// пока нет подписки на заявки или шаблона отклика, — «Первые шаги» (UX №9).
// Блоки артборда, чьих экранов ещё нет, появятся со своими шагами: «За 30 дней» и «Скоро» — v1.
import type { HintOut, ProfileOut } from '@sosed/api-client';
import { availableUntil, quickHour } from '@sosed/domain';
import type { ProfileState } from '@sosed/hooks';
import {
  REVIEW_INVITES_LIMIT,
  becomeStep,
  profileState,
  useMyPortfolio,
  useMyProfile,
  useJobAlerts,
  useMyServices,
  useResponseTemplates,
  useReviewInvites,
  useSetAvailability,
} from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { IconName } from '@sosed/ui-web';
import {
  Button,
  Card,
  Group,
  Heading,
  Icon,
  ProgressBar,
  Row,
  SectionTitle,
  Switch,
  Text,
  cx,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useEffect, useId } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useBecomeFlow, useStepButton } from '../shared/flow.ts';
import { ACCOUNT_PATH, CABINET_PATHS } from '../shared/paths.ts';

/** Публичный профиль S08, как его видят клиенты (маршрут features/catalog). */
const PUBLIC_PROFILE_PATH = '/specialists/$profileId';
/** Новая подписка на заявки S19 и шаблоны откликов S57 (маршруты features/jobs). */
const NEW_ALERT_PATH = '/jobs/alerts/new';
const TEMPLATES_PATH = '/jobs/responses/templates';

/** Причины отказа модерации, у которых есть свой текст; остальные — «нарушение правил». */
const REASONS = [
  'prepayment_scam',
  'off_platform_payment',
  'mule_recruitment',
  'prohibited',
  'contact_leak',
  'spam_ad',
  'vacancy',
  'other',
] as const;
/** Запрещённое называем одним словом, как в уведомлении бота (ADR-0016). */
const PROHIBITED: ReadonlySet<string> = new Set(['drug_courier', 'sexual_services', 'weapons']);

function reasonOf(code: string | null): (typeof REASONS)[number] {
  if (code !== null && PROHIBITED.has(code)) return 'prohibited';
  return REASONS.find((known) => known === code) ?? 'other';
}

const STATE_ICONS: Record<ProfileState, { icon: IconName; tone: string }> = {
  published: { icon: 'check-circle', tone: 'text-accent' },
  pending_review: { icon: 'clock', tone: 'text-info-ink' },
  draft: { icon: 'edit', tone: 'text-text2' },
  rejected: { icon: 'alert', tone: 'text-danger' },
  hidden: { icon: 'eye', tone: 'text-text2' },
  suspended: { icon: 'ban', tone: 'text-danger' },
};

export function CabinetScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: ACCOUNT_PATH, replace: true });
  });
  // профиля нет (кабинет открыли по ссылке) — вход в мастер на S31
  useEffect(() => {
    if (profile.data === null) void router.navigate({ to: ACCOUNT_PATH, replace: true });
  }, [profile.data, router]);

  if (profile.data) return <Cabinet profile={profile.data} />;
  return (
    <section className="flex flex-col gap-3 px-4 pt-2 pb-6">
      <Heading variant="h2" as="h1">
        {t('cabinet.title')}
      </Heading>
      <LoadState
        shape="cabinet"
        error={profile.isError ? profile.error : null}
        onRetry={() => void profile.refetch()}
        retrying={profile.isFetching}
      />
    </section>
  );
}

function Cabinet({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const flow = useBecomeFlow();
  const state = profileState(profile);
  const step = becomeStep(profile);
  const { icon, tone } = STATE_ICONS[state];
  const stateKey =
    state === 'published' && !profile.listed_in_catalog ? 'publishedUnlisted' : state;
  const stateText =
    stateKey === 'rejected'
      ? t('cabinet.state.rejected', {
          reason: t(`cabinet.reason.${reasonOf(profile.rejection_reason)}`),
        })
      : t(`cabinet.state.${stateKey}`);
  const { percent, hints } = profile.completeness;
  const pending = profile.status === 'pending_review';

  // черновик — дописать в мастере; на проверке ждать, но можно добавить фото работ — с ними
  // выбирают чаще; MainButton — главное действие экрана, как в Telegram
  useStepButton({
    text: t(
      state === 'rejected' ? 'cabinet.fix' : pending ? 'cabinet.addPhotos' : 'cabinet.continue',
    ),
    onClick: () => {
      if (pending) void router.navigate({ to: CABINET_PATHS.portfolio });
      else if (step) flow.open(step);
    },
    visible: step !== null || pending,
  });

  const open =
    (
      to: (typeof CABINET_PATHS)[
        'profile' | 'availability' | 'prices' | 'portfolio' | 'reviewInvites'],
    ) =>
    (event: MouseEvent<HTMLElement>) => {
      event.preventDefault();
      void router.navigate({ to });
    };
  // доступность и пауза — у профиля, который видят клиенты
  const visible = profile.status === 'published' || profile.status === 'hidden';

  return (
    <section className="flex flex-col gap-2.5 px-4 pt-2 pb-6">
      <Card as="section">
        <div className="flex flex-col gap-1">
          <Heading variant="h2" as="h1">
            {t(profile.kind === 'pro' ? 'cabinet.title' : 'cabinet.casualTitle')}
          </Heading>
          {/* строка «на проверке» переносится — иконка у первой строки, а не посередине */}
          <Text variant="sm" className="flex items-start gap-1.5">
            <Icon name={icon} size={16} className={cx('mt-0.5 shrink-0', tone)} />
            {stateText}
          </Text>
        </div>
        <div className="flex flex-col gap-2">
          <Text variant="sm" bold>
            {t('cabinet.filled', { percent })}
          </Text>
          <ProgressBar value={percent} label={t('cabinet.filledLabel')} />
          <Text variant="cap">
            {hints[0] ? <HintText hint={hints[0]} /> : t('cabinet.complete')}
          </Text>
        </div>
        {profile.status === 'published' && (
          <>
            <AvailableToday profile={profile} />
            <Button
              variant="outline"
              full
              icon="eye"
              onClick={() =>
                void router.navigate({
                  to: PUBLIC_PROFILE_PATH,
                  params: { profileId: profile.id },
                })
              }
            >
              {t('cabinet.viewAsClient')}
            </Button>
          </>
        )}
      </Card>
      {profile.status === 'published' && <FirstSteps />}
      <nav aria-label={t('cabinet.manage')}>
        <Group>
          <Row
            icon="user"
            title={t('cabinet.profile')}
            chevron
            href={router.history.createHref(CABINET_PATHS.profile)}
            onClick={open(CABINET_PATHS.profile)}
          />
          <Row
            icon="list"
            title={t('cabinet.prices')}
            trailing={<PriceCount />}
            chevron
            href={router.history.createHref(CABINET_PATHS.prices)}
            onClick={open(CABINET_PATHS.prices)}
          />
          <Row
            icon="image"
            title={t('cabinet.portfolio')}
            trailing={<WorkCount />}
            chevron
            href={router.history.createHref(CABINET_PATHS.portfolio)}
            onClick={open(CABINET_PATHS.portfolio)}
          />
          {visible && (
            <Row
              icon="calendar"
              title={t('cabinet.availability')}
              trailing={<AvailabilityValue profile={profile} />}
              chevron
              href={router.history.createHref(CABINET_PATHS.availability)}
              onClick={open(CABINET_PATHS.availability)}
            />
          )}
          {visible && (
            <Row
              icon="users"
              title={t('cabinet.invites')}
              trailing={<InviteCount />}
              chevron
              href={router.history.createHref(CABINET_PATHS.reviewInvites)}
              onClick={open(CABINET_PATHS.reviewInvites)}
            />
          )}
        </Group>
      </nav>
    </section>
  );
}

/** «Первые шаги» опубликованного (UX №9): подписка на заявки и шаблон отклика — то, что приводит
 *  заявки. Сделанный шаг пропадает, оба сделаны — пропадает блок; пока списки грузятся, блока нет,
 *  чтобы он не мигал у тех, кому уже не нужен. */
function FirstSteps() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const alerts = useJobAlerts();
  const templates = useResponseTemplates();
  const titleId = useId();
  if (!alerts.data || !templates.data) return null;
  const needAlerts = alerts.data.items.length === 0;
  const needTemplate = templates.data.items.length === 0;
  if (!needAlerts && !needTemplate) return null;
  const open = (to: typeof NEW_ALERT_PATH | typeof TEMPLATES_PATH) => ({
    href: router.history.createHref(to),
    onClick: (event: MouseEvent<HTMLElement>) => {
      event.preventDefault();
      void router.navigate({ to });
    },
  });
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2">
      <SectionTitle id={titleId}>{t('cabinet.steps')}</SectionTitle>
      <Group>
        {needAlerts && (
          <Row
            icon="bell"
            title={t('cabinet.stepAlerts')}
            subtitle={t('cabinet.stepAlertsText')}
            chevron
            {...open(NEW_ALERT_PATH)}
          />
        )}
        {needTemplate && (
          <Row
            icon="file"
            title={t('cabinet.stepTemplate')}
            subtitle={t('cabinet.stepTemplateText')}
            chevron
            {...open(TEMPLATES_PATH)}
          />
        )}
      </Group>
    </section>
  );
}

const HINT_CODES = [
  'category_ids',
  'headline',
  'about',
  'languages',
  'area_ids',
  'services',
  'service_descriptions',
  'portfolio',
  'avatar',
] as const;

/** Подсказка полноты по коду сервера; незнакомый код (новый backend) — без подсказки. */
function HintText({ hint }: { hint: HintOut }) {
  const { t } = useTranslation('specialist');
  const code = HINT_CODES.find((known) => known === hint.code);
  if (!code) return null;
  return (
    <span className={cx(hint.count !== null && 'tabular-nums')}>
      {t(`cabinet.hint.${code}`, { count: hint.count ?? 0 })}
    </span>
  );
}

/** «Доступен сегодня до …» в карточке: переключатель включает «до 20:00» или ближайший вариант. */
function AvailableToday({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const format = useFormat();
  const platform = usePlatform();
  const setAvailability = useSetAvailability();
  const now = new Date();
  const until = availableUntil(profile.available_until, now);
  const quick = quickHour(now);
  const toggle = (on: boolean) => {
    platform.haptics.selection();
    setAvailability.mutate(on ? quick : null);
  };
  const label = until
    ? t('cabinet.availableUntil', { time: format.time(until) })
    : t('cabinet.availableToday');
  return (
    <>
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 text-body">{label}</span>
        <Switch
          checked={until !== null}
          onChange={toggle}
          label={label}
          disabled={setAvailability.isPending || (until === null && quick === null)}
        />
      </div>
      {until === null && quick === null && <Text variant="cap">{t('availability.todayLate')}</Text>}
      {setAvailability.isError && <SaveError error={setAvailability.error} />}
    </>
  );
}

/** Значение строки «Доступность»: «сегодня до 20:00» или «выключено». */
function AvailabilityValue({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const format = useFormat();
  const until = availableUntil(profile.available_until, new Date());
  return (
    <Text as="span" variant="sm" secondary>
      {until
        ? t('cabinet.availabilityValue', { time: format.time(until) })
        : t('cabinet.availabilityOff')}
    </Text>
  );
}

/** Сколько позиций в прайсе — справа в строке «Прайс», как на артборде. */
function PriceCount() {
  const services = useMyServices();
  const count = services.data?.items.length;
  if (!count) return null;
  return (
    <Text as="span" variant="sm" secondary>
      {count}
    </Text>
  );
}

/** Сколько мест под приглашения на «отзыв до платформы» занято — «2 из 5», как на артборде. */
function InviteCount() {
  const { t } = useTranslation('specialist');
  const invites = useReviewInvites();
  const taken = invites.data?.taken;
  if (!taken) return null;
  return (
    <Text as="span" variant="sm" secondary>
      {t('cabinet.invitesValue', { taken, limit: invites.data?.limit ?? REVIEW_INVITES_LIMIT })}
    </Text>
  );
}

/** Сколько работ в портфолио — справа в строке «Портфолио», как на артборде. */
function WorkCount() {
  const portfolio = useMyPortfolio();
  const count = portfolio.data?.items.length;
  if (!count) return null;
  return (
    <Text as="span" variant="sm" secondary>
      {count}
    </Text>
  );
}
