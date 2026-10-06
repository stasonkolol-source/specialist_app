// S24 Отклик глазами клиента и S25 подтверждение выбора (DEVELOPMENT_PLAN 6.2): мини-профиль
// исполнителя (фото, имя, рейтинг со звездой или «Новый специалист», «Телефон подтверждён»,
// «Откликнулся первым»; профиль специалиста — ссылкой на S08), предложение — цена, «Когда сможет»,
// сообщение и нижней строкой «Ваш бюджет — …» и «Отклонить»: после подтверждения место
// освобождается. MainButton «Выбрать исполнителем» открывает шторку S25: что изменится сразу
// (адрес исполнителю, уведомление остальным) плоским списком, «если сделка сорвётся — заявка
// снова откроется»; подтверждение создаёт сделку и ведёт на S26. Решённый
// отклик — словами («Вы отклонили…», «Выбран другой исполнитель»), выбранный — «Открыть сделку».
// SecondaryButton «Написать» (6.4) — диалог по отклику S30 (на клиентах без SecondaryButton —
// кнопкой в контенте). Отклик берётся из карточек S23 (уже в кэше). Последние отзывы (7.2) — в
// своём шаге.
import type { JobOut, ResponseCardOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import {
  isUnavailable,
  useAcceptResponse,
  useDeclineResponse,
  useJob,
  useMyDeals,
  useResponseCards,
  useStartConversation,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import {
  useBackButton,
  useBottomButtonState,
  usePlatform,
  useSecondaryButton,
} from '@sosed/platform';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Heading,
  Icon,
  LinkButton,
  Price,
  Sheet,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
} from '@sosed/ui-web';
import { Navigate, useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { useStepButton } from '../shared/flow.ts';
import { JobUnavailable } from '../shared/JobUnavailable.tsx';
import { useBudgetText, useOfferPrice, usePerformerPlace } from '../shared/labels.ts';
import { LoadError } from '../shared/LoadError.tsx';
import { PerformerRating } from '../shared/PerformerRating.tsx';
import {
  JOBS_PATHS,
  chatPath,
  dealPath,
  jobIdOf,
  jobPath,
  managePath,
  specialistPath,
} from '../shared/paths.ts';

/** Отклик ждёт решения клиента — его можно выбрать или отклонить. */
const OPEN: ReadonlySet<ResponseCardOut['status']> = new Set([
  'submitted',
  'viewed',
  'shortlisted',
]);

export function ChoiceScreen() {
  const { jobId: rawJob = '', responseId = '' } = useParams({ strict: false });
  const jobId = jobIdOf(rawJob);
  const router = useRouter();
  const job = useJob(jobId);
  const cards = useResponseCards(jobId);
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else if (jobId) void router.navigate({ to: managePath(jobId), replace: true });
    else void router.navigate({ to: JOBS_PATHS.mine, replace: true });
  });

  if (jobId === null || (job.isError && isUnavailable(job.error))) {
    return <JobUnavailable onFeed={() => void router.navigate({ to: JOBS_PATHS.mine })} />;
  }
  const failed = job.error ?? cards.error;
  if (failed && !(job.data && cards.data)) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={failed}
          onRetry={() => {
            if (job.isError) void job.refetch();
            if (cards.isError) void cards.refetch();
          }}
          retrying={job.isRefetching || cards.isRefetching}
        />
      </section>
    );
  }
  if (!job.data || !cards.data) return <Loading />;
  if (job.data.viewer_role !== 'owner') return <Navigate to={jobPath(job.data.id)} replace />;
  const card = cards.data.items.find((item) => item.id === responseId);
  if (!card) return <Gone jobId={job.data.id} />;
  return <Choice job={job.data} card={card} others={cards.data.items.length - 1} />;
}

function Choice({ job, card, others }: { job: JobOut; card: ResponseCardOut; others: number }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const platform = usePlatform();
  const budgetText = useBudgetText();
  const decline = useDeclineResponse();
  const [confirming, setConfirming] = useState(false);
  const open = job.status === 'published' && OPEN.has(card.status);
  const budget = budgetText(job);
  const offerId = useId();
  // пока открыта шторка S25, нижняя панель у неё (BottomBar): «Написать» экрана прячется сама
  useStepButton({
    text: t('choice.choose'),
    visible: open,
    enabled: !decline.isPending,
    onClick: () => setConfirming(true),
  });
  const write = useWrite(card);
  // отказ необратим — сначала нативное подтверждение, как «Отозвать отклик» на S17
  const reject = async () => {
    if (!(await platform.confirm(t('choice.declineConfirm')))) return;
    decline.mutate(
      { jobId: job.id, responseId: card.id },
      { onSuccess: () => void router.navigate({ to: managePath(job.id), replace: true }) },
    );
  };

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <Performer card={card} />
      <Card as="section" tight aria-labelledby={offerId}>
        <Heading variant="h3" as="h2" id={offerId}>
          {t('choice.offer')}
        </Heading>
        <Offer card={card} />
        {card.message && (
          <Text variant="sm" className="whitespace-pre-line">
            {t('respond.quoted', { message: card.message })}
          </Text>
        )}
        {/* нижняя строка карточки, как на артборде: бюджет слева, «Отклонить» справа */}
        {(budget || open) && (
          <div className="flex items-center justify-between gap-3">
            {budget && (
              <Text as="span" variant="cap">
                {t('choice.budget', { amount: budget })}
              </Text>
            )}
            {open && (
              <LinkButton
                danger
                className="-mr-2 ml-auto"
                disabled={decline.isPending}
                onClick={() => void reject()}
              >
                {t('choice.decline')}
              </LinkButton>
            )}
          </div>
        )}
      </Card>
      {write.available && !write.native && (
        <Button
          variant="secondary"
          full
          onClick={write.start}
          disabled={write.pending}
          aria-busy={write.pending}
        >
          {write.label}
        </Button>
      )}
      {write.error && <ActionError error={write.error} fallback={t('choice.writeError')} />}
      {decline.error && <ActionError error={decline.error} fallback={t('choice.declineError')} />}
      {!open && <Decided job={job} card={card} />}
      {confirming && (
        <ConfirmSheet job={job} card={card} others={others} onClose={() => setConfirming(false)} />
      )}
    </section>
  );
}

/** «Написать»: диалог по отклику — начать или открыть начатый; отозванному писать некуда. */
function useWrite(card: ResponseCardOut) {
  const { t: common } = useTranslation();
  const router = useRouter();
  const start = useStartConversation();
  const available = card.status !== 'withdrawn';
  const begin = () =>
    start.mutate(
      { response_id: card.id },
      { onSuccess: (started) => void router.navigate({ to: chatPath(started.id) }) },
    );
  const { native } = useSecondaryButton({
    text: common('action.write'),
    visible: available,
    enabled: !start.isPending,
    loading: start.isPending,
    onClick: begin,
  });
  return {
    available,
    native,
    label: common('action.write'),
    start: begin,
    pending: start.isPending,
    error: start.error,
  };
}

/** Мини-профиль: фото, имя, рейтинг, бейджи; профиль специалиста — ссылкой на S08. */
function Performer({ card }: { card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const { performer } = card;
  const name = performer.display_name || '—';
  const avatar =
    performer.avatar?.variants.find((v) => v.name === 'thumb') ?? performer.avatar?.variants[0];
  const profile = performer.profile_id;
  const place = usePerformerPlace(performer);
  return (
    <Card
      tight
      href={profile ? router.history.createHref(specialistPath(profile)) : undefined}
      onClick={
        profile
          ? (event) => {
              event.preventDefault();
              void router.navigate({ to: specialistPath(profile) });
            }
          : undefined
      }
      aria-label={profile ? `${name}: ${t('choice.profile')}` : undefined}
    >
      <div className="flex items-center gap-3">
        <Avatar
          name={name}
          size="lg"
          src={avatar?.url}
          placeholder={performer.avatar?.placeholder}
        />
        <div className="flex min-w-0 grow flex-col gap-1">
          <Heading variant="h2" as="h1">
            {name}
          </Heading>
          {/* «Новый специалист» — в строке рейтинга, отдельным бейджем не повторяем */}
          <PerformerRating
            rating={performer.rating}
            count={performer.rating_count}
            meta={[place]}
          />
        </div>
        {profile && <Icon name="chev-right" className="shrink-0 text-text2" />}
      </div>
      {(performer.phone_verified || card.is_first || performer.kind !== 'pro') && (
        <div className="flex flex-wrap gap-1.5">
          {performer.phone_verified && (
            <Badge tone="info" icon="shield">
              {t('manage.phone')}
            </Badge>
          )}
          {card.is_first && <Badge tone="ok">{t('manage.first')}</Badge>}
          {performer.kind !== 'pro' && <Badge>{t('manage.casual')}</Badge>}
        </div>
      )}
    </Card>
  );
}

/** Цена и «Когда сможет» рядами: подпись слева, значение справа. */
function Offer({ card }: { card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const offerPrice = useOfferPrice();
  const price = card.price.type === 'negotiable' ? t('card.negotiable') : offerPrice(card.price);
  return (
    <dl className="m-0 flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-text2">{t(`choice.price.${card.price.type}`)}</dt>
        <dd className="m-0">
          <Price>{price}</Price>
        </dd>
      </div>
      {card.availability_note && (
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-text2">{t('choice.when')}</dt>
          <dd className="m-0 text-right font-semibold">{card.availability_note}</dd>
        </div>
      )}
    </dl>
  );
}

/** Отклик уже решён: словами, а выбранному — «Открыть сделку». */
function Decided({ job, card }: { job: JobOut; card: ResponseCardOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const deals = useMyDeals({ role: 'client' });
  const deal = deals.data?.items.find((item) => item.response_id === card.id);
  if (OPEN.has(card.status)) {
    // отклик ждёт решения, но заявка уже не принимает выбор: закрыта, истекла, на проверке
    return (
      <Banner tone="info" role="status">
        {t(`mine.status.${job.status}`)}
      </Banner>
    );
  }
  const accepted = card.status === 'accepted';
  return (
    <div className="flex flex-col gap-2.5">
      <Banner tone={accepted ? 'ok' : 'info'} role="status">
        {t(`choice.state.${decidedState(card.status)}`)}
      </Banner>
      {accepted && deal && (
        <Button
          variant="secondary"
          full
          onClick={() => void router.navigate({ to: dealPath(deal.id) })}
        >
          {t('choice.openDeal')}
        </Button>
      )}
    </div>
  );
}

type Decision = 'accepted' | 'declined' | 'withdrawn' | 'not_selected';

function decidedState(status: ResponseCardOut['status']): Decision {
  if (status === 'accepted' || status === 'declined' || status === 'withdrawn') return status;
  return 'not_selected';
}

/** S25: кого выбираем, условия, что изменится сразу; подтверждение — сделка и S26. */
function ConfirmSheet({
  job,
  card,
  others,
  onClose,
}: {
  job: JobOut;
  card: ResponseCardOut;
  others: number;
  onClose: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const router = useRouter();
  const offerPrice = useOfferPrice();
  const accept = useAcceptResponse();
  const button = useBottomButtonState('main');
  const changesId = useId();
  useBackButton(onClose);
  const { performer } = card;
  const name = performer.display_name || '—';
  const avatar =
    performer.avatar?.variants.find((v) => v.name === 'thumb') ?? performer.avatar?.variants[0];
  const price = card.price.type === 'negotiable' ? t('card.negotiable') : offerPrice(card.price);
  const terms = [price, card.availability_note].filter(Boolean).join(' · ');
  // Promise в MainButton: пока выбор идёт, второе нажатие (двойной тап) не уходит (MU-5)
  useStepButton({
    text: t('choice.confirm'),
    loading: accept.isPending,
    onClick: () =>
      accept
        .mutateAsync({ jobId: job.id, responseId: card.id })
        .then((accepted) => router.navigate({ to: dealPath(accepted.deal_id), replace: true }))
        .catch(() => undefined), // ошибка — баннером в шторке
  });
  return (
    <Sheet
      open
      title={t('choice.confirmTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
      closeButton={false}
    >
      <div className="flex items-center gap-3">
        <Avatar name={name} src={avatar?.url} placeholder={performer.avatar?.placeholder} />
        <div className="flex min-w-0 flex-col">
          <span className="text-title">{name}</span>
          <Text as="span" variant="cap">
            {terms}
          </Text>
        </div>
      </div>
      {/* плоским списком, как на артборде: карточка в шторке сливается с фоном в светлой теме */}
      <section className="flex flex-col gap-2.5" aria-labelledby={changesId}>
        <h3 id={changesId} className="m-0 text-sm font-semibold">
          {t('choice.changes')}
        </h3>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          <li className="flex items-start gap-2.5">
            <Icon name="pin" size={20} className="shrink-0 text-accent" />
            <Text as="span" variant="sm">
              {t('choice.changeAddress')}
            </Text>
          </li>
          {others > 0 && (
            <li className="flex items-start gap-2.5">
              <Icon name="bell" size={20} className="shrink-0 text-accent" />
              <Text as="span" variant="sm">
                {t('choice.changeOthers')}
              </Text>
            </li>
          )}
        </ul>
      </section>
      <Text variant="cap">{t('choice.note')}</Text>
      {accept.error && <ActionError error={accept.error} fallback={t('choice.acceptError')} />}
      <Button variant="outline" full disabled={accept.isPending} onClick={onClose}>
        {t('choice.cancel')}
      </Button>
      {!button.native && <div className="h-19" aria-hidden="true" />}
    </Sheet>
  );
}

function Gone({ jobId }: { jobId: string }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  return (
    <section className="px-4 pt-6">
      <EmptyState as="h1" icon="ban" title={t('choice.unavailable')}>
        <Text variant="sm">{t('choice.unavailableText')}</Text>
        <Button
          variant="secondary"
          onClick={() => void router.navigate({ to: managePath(jobId), replace: true })}
        >
          {t('responses.open')}
        </Button>
      </EmptyState>
    </section>
  );
}

/** Ошибка действия: 4xx — текстом сервера, остальное — «повторите». */
function ActionError({ error, fallback }: { error: unknown; fallback: string }) {
  const detail = error instanceof ApiError && error.status < 500 ? error.problem.detail : null;
  return (
    <Banner tone="danger" role="alert">
      {detail ?? fallback}
    </Banner>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      {/* исполнитель: фото, имя, рейтинг */}
      <SkeletonCard>
        <div className="flex items-center gap-3">
          <Skeleton round className="size-22 shrink-0" />
          <div className="flex min-w-0 grow flex-col gap-1">
            <SkeletonText size="h2" className="w-3/5" />
            <SkeletonText size="cap" className="w-1/2" />
          </div>
        </div>
      </SkeletonCard>
      {/* предложение: цена, сроки, сообщение */}
      <SkeletonCard tight>
        <SkeletonText size="h3" className="w-1/3" />
        <SkeletonText size="title" className="w-1/4" />
        <div className="flex flex-col">
          <SkeletonText size="sm" className="w-full" />
          <SkeletonText size="sm" className="w-3/4" />
        </div>
      </SkeletonCard>
      <Skeleton radius="field" screen className="h-11 w-full" />
    </section>
  );
}
