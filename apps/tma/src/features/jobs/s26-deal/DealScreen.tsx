// S26 Сделка (DEVELOPMENT_PLAN 6.2): название, статус («Договорились», «Выполнена», «Отменена»),
// время и цена; вторая сторона — фото, имя, рейтинг или «Новый специалист», роль (профиль
// специалиста — ссылкой на S08); адрес — сторонам («адрес видите только вы и …»), копировать;
// таймлайн «Отклик на заявку → Выбран исполнителем → Договорились (работа …) → Работа выполнена →
// Отзыв» — текущий шаг и следующий, остальные под «Подробнее»; памятка о предоплате клиенту — одной
// строкой. Под заголовком у идущей сделки — что дальше («Исполнителю пришло уведомление.
// Договоритесь о времени и адресе в чате.», UX_GUIDANCE №2). MainButton — следующий шаг по времени:
// «Написать» (чат сделки, S30), а «Работа выполнена» — когда бот спрашивает о ней
// (`completion_due_at`) или вторая сторона уже отметила; раньше — строка «Работа уже сделана?
// Отметить». Отметка стороны — вторая завершает сделку (или сама через 3 дня); «Отменить сделку»
// спрашивает причину — заявка снова открыта; после любой отметки отменить нельзя (MU-8). Данные —
// BFF `GET /deals/{id}/card`. «Договориться» из чата (6.5): второй стороне — S53 «… предлагает
// договориться» с условиями, сроком (72 ч) и «Подтвердить» / «Отклонить», предложившей — «ждём
// подтверждения». После договорённости — контакты: Telegram второй стороны (если она его
// показывает) и «Поделиться контактом» — шторка S54 в чате сделки. «Есть проблема» → спор S52
// (6.1c) — строкой внизу, рядом с «Отменить сделку»; под спором — «сделка на паузе» и «Спор по
// сделке», после решения — «Решение по спору». Завершена (7.3): итог без адреса и таймлайна,
// MainButton «Оставить отзыв» (S27) клиенту, пока окно открыто, и статус своего отзыва; клиенту —
// «Заказать снова»: прямой диалог с этим специалистом, где в шапке «Договориться» (S30).
import type { DealCancelReason, DealCardOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import {
  isUnavailable,
  useAnswerProposal,
  useCancelDeal,
  useCompleteDeal,
  useDealCard,
  useStartConversation,
} from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform, useSecondaryButton } from '@sosed/platform';
import type { IconName, TimelineItem } from '@sosed/ui-web';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Group,
  Heading,
  Icon,
  IconButton,
  LinkButton,
  Price,
  Row,
  RowIcon,
  Sheet,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Text,
  Timeline,
  cx,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { useStepButton } from '../shared/flow.ts';
import { useOfferPrice } from '../shared/labels.ts';
import { LoadError } from '../shared/LoadError.tsx';
import { PerformerRating } from '../shared/PerformerRating.tsx';
import {
  JOBS_PATHS,
  chatPath,
  disputePath,
  jobIdOf,
  reviewPath,
  specialistPath,
} from '../shared/paths.ts';

/** Статус своего отзыва (7.3): API отдаёт строкой. */
type ReviewState = 'under_review' | 'published' | 'removed';
/** Причины, которые выбирает сторона; `expired` и `account_deleted` ставит система. */
type PartyReason = Extract<
  DealCancelReason,
  'plans_changed' | 'no_agreement' | 'no_contact' | 'other'
>;
const REASONS: readonly PartyReason[] = ['plans_changed', 'no_agreement', 'no_contact', 'other'];
const STATUS_TONE = {
  proposed: 'info',
  agreed: 'ok',
  completed: 'ok',
  cancelled: undefined,
  disputed: 'urgent',
} as const;
/** Причины стороны: остальные (`expired`, `account_deleted`) — своим текстом. */
const PARTY_REASONS: ReadonlySet<string> = new Set(REASONS);

export function DealScreen() {
  const { dealId: raw = '' } = useParams({ strict: false });
  const dealId = jobIdOf(raw);
  const router = useRouter();
  // ждём вторую сторону: её отметки, отмена и спор — без перехода (MU-4)
  const card = useDealCard(dealId, { live: true });
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: JOBS_PATHS.mine, replace: true });
  });

  if (dealId === null || (card.isError && isUnavailable(card.error))) return <Gone />;
  if (card.isError) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={card.error}
          onRetry={() => void card.refetch()}
          retrying={card.isRefetching}
        />
      </section>
    );
  }
  if (!card.data) return <Loading />;
  if (card.data.awaits_my_confirmation) return <Proposal deal={card.data} />;
  return <Deal deal={card.data} />;
}

/** S53: вторая сторона предложила договориться — значок, условия строками с иконками, срок и
 *  ответ: MainButton «Подтвердить», SecondaryButton «Отклонить» под ней, как на артборде (до Bot
 *  API 7.10 — кнопкой в контенте). */
function Proposal({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const offerPrice = useOfferPrice();
  const router = useRouter();
  const answer = useAnswerProposal();
  const name = deal.counterpart.display_name;
  const when = deal.scheduled_at
    ? format.calendar(new Date(deal.scheduled_at))
    : deal.availability_note;
  const price =
    deal.price.type === null || deal.price.type === 'negotiable'
      ? t('card.negotiable')
      : offerPrice({ type: deal.price.type, amount: deal.price.amount });
  const district = deal.place.district?.name ?? deal.place.city?.name ?? null;
  // Promise в кнопках: пока ответ уходит, второе нажатие (двойной тап) не уходит (MU-5)
  useStepButton({
    text: t('deal.proposal.confirm'),
    loading: answer.isPending,
    onClick: () => answer.mutateAsync({ dealId: deal.id, confirm: true }).catch(() => undefined),
  });
  const decline = () =>
    answer
      .mutateAsync({ dealId: deal.id, confirm: false })
      .then(() => {
        if (router.history.canGoBack()) router.history.back();
      })
      .catch(() => undefined); // ошибка — баннером
  const { native } = useSecondaryButton({
    text: t('deal.proposal.decline'),
    enabled: !answer.isPending,
    onClick: decline,
    position: 'bottom',
  });
  return (
    <section className="flex flex-col gap-4 px-4 pt-5 pb-6">
      <div className="flex flex-col items-center gap-3 text-center">
        <span
          aria-hidden="true"
          className="flex size-18 items-center justify-center rounded-full bg-accent-soft text-accent-soft-ink"
        >
          <Icon name="check-circle" size={32} />
        </span>
        <Heading variant="h2" as="h1">
          {name ? t('deal.proposal.title', { name }) : t('deal.proposal.titleNoName')}
        </Heading>
        <Text secondary>{t('deal.proposal.text')}</Text>
      </div>
      <section aria-label={deal.title}>
        <Group>
          <Term icon="wrench" label={t('deal.proposal.what')}>
            {deal.title}
          </Term>
          {when && (
            <Term icon="calendar" label={t('deal.proposal.when')}>
              {when}
            </Term>
          )}
          {district && (
            <Term
              icon="pin"
              label={t('deal.proposal.where')}
              note={t('deal.proposal.addressLater')}
              narrowNote
            >
              {district}
            </Term>
          )}
          <Term
            icon="wallet"
            label={t('deal.proposal.price')}
            detail={
              deal.proposed_at
                ? t('deal.proposal.proposedAt', {
                    time: format.calendarGenitive(new Date(deal.proposed_at)),
                  })
                : undefined
            }
          >
            <Price>{price}</Price>
          </Term>
        </Group>
      </section>
      {deal.proposal_expires_at && (
        <Banner tone="info" icon="clock">
          {t('deal.proposal.expires', {
            date: format.calendarGenitive(new Date(deal.proposal_expires_at)),
          })}
        </Banner>
      )}
      {answer.error && (
        <ActionError error={answer.error} fallback={t('deal.proposal.answerError')} />
      )}
      {!native && (
        <Button variant="secondary" full disabled={answer.isPending} onClick={decline}>
          {t('deal.proposal.decline')}
        </Button>
      )}
    </section>
  );
}

/** Строка условий (.row): иконка, подпись над значением, справа — пояснение мелко; `detail` —
 *  второй строкой под значением. */
function Term({
  icon,
  label,
  note,
  detail,
  narrowNote = false,
  children,
}: {
  icon: IconName;
  label: string;
  note?: string;
  /** Под значением: «предложено сегодня в 10:00» справа наезжало на крупную сумму. */
  detail?: string;
  /** Длинное пояснение — колонкой до 140 px, как «точный адрес — после подтверждения». */
  narrowNote?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 border-0 border-b border-solid border-line px-4 py-3 last:border-b-0">
      <RowIcon icon={icon} />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-cap text-text2">{label}</span>
        <span className="font-semibold">{children}</span>
        {detail && <span className="text-cap text-text2">{detail}</span>}
      </div>
      {note && (
        <span className={cx('text-right text-cap text-text2', narrowNote && 'max-w-35')}>
          {note}
        </span>
      )}
    </div>
  );
}

/** Сделка идёт: договориться в чате можно и нужно — главная кнопка «Написать». */
const CHATTING: ReadonlySet<DealCardOut['status']> = new Set(['proposed', 'agreed', 'disputed']);

/** Время уже наступило (`completion_due_at`: бот спрашивает «Работа выполнена?»). */
const isPast = (at: string | null) => at !== null && Date.parse(at) <= Date.now();

function Deal({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const format = useFormat();
  const complete = useCompleteDeal();
  const cancel = useCancelDeal();
  const chat = useDealChat(deal);
  const card = useDealCard(deal.id);
  const [cancelling, setCancelling] = useState(false);
  const agreed = deal.status === 'agreed';
  const client = deal.my_role === 'client';
  const router = useRouter();
  const { timeline } = deal;
  const failed = complete.error ?? cancel.error ?? chat.error;
  const reviewing = deal.status === 'completed' && deal.review_until !== null;
  // отметили «Работа выполнена» — отменить уже нельзя: подтвердить или спор (MU-8)
  const marked = timeline.my_mark_at !== null || timeline.other_mark_at !== null;
  const canMark = agreed && timeline.my_mark_at === null && !cancelling;
  // «Работа выполнена» — главная, когда пора: бот уже спрашивает о ней или вторая сторона
  // отметила; до этого следующий шаг — договориться о времени и адресе в чате (UX_GUIDANCE №2)
  const due = canMark && (timeline.other_mark_at !== null || isPast(deal.completion_due_at));
  const writing = !reviewing && !due && chat.available && CHATTING.has(deal.status);
  const markDone = () => complete.mutateAsync(deal.id).catch(() => undefined); // ошибка — баннером
  useStepButton(
    reviewing
      ? {
          text: t('deal.leaveReview'),
          visible: true,
          loading: false,
          onClick: () => void router.navigate({ to: reviewPath(deal.id) }),
        }
      : due
        ? // Promise: пока отметка уходит, второе нажатие не уходит (MU-5)
          {
            text: t('deal.complete'),
            visible: true,
            loading: complete.isPending,
            onClick: markDone,
          }
        : {
            text: common('action.write'),
            visible: writing && !cancelling,
            loading: chat.pending,
            onClick: chat.write,
          },
  );
  const cancelPick = (reason: PartyReason) =>
    cancel.mutate(
      { dealId: deal.id, reason },
      {
        onSettled: () => setCancelling(false),
        // вторая сторона успела отметить «Работа выполнена» — карточка покажет её отметку (MU-8)
        onError: (error) => {
          if (error instanceof ApiError && error.code === MARKED_DONE) void card.refetch();
        },
      },
    );

  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Header deal={deal} />
      {deal.status === 'proposed' && deal.proposal_expires_at && (
        <Banner tone="info">
          {t('deal.proposal.waiting', {
            date: format.calendarGenitive(new Date(deal.proposal_expires_at)),
          })}
        </Banner>
      )}
      <Counterpart deal={deal} />
      {(agreed || deal.status === 'disputed' || deal.status === 'completed') && (
        <Contacts deal={deal} chat={chat} write={!writing && deal.status !== 'completed'} />
      )}
      {/* выполненной сделке адрес и «Поделиться контактом» уже ни к чему (№13) */}
      {deal.status !== 'completed' && <Address deal={deal} />}
      {deal.status !== 'completed' && deal.status !== 'cancelled' && <Steps deal={deal} />}
      <State deal={deal} />
      {deal.status === 'completed' && client && deal.counterpart.profile_id && (
        <OrderAgain profileId={deal.counterpart.profile_id} />
      )}
      {failed && (
        <ActionError
          error={failed}
          fallback={
            complete.error
              ? t('deal.completeError')
              : cancel.error
                ? t('deal.cancelError')
                : t('deal.contacts.shareError')
          }
        />
      )}
      {agreed && client && <SafetyLine>{t('deal.safety')}</SafetyLine>}
      <Actions
        deal={deal}
        early={canMark && !due}
        onMark={() => void markDone()}
        cancellable={(agreed || deal.status === 'proposed') && !marked}
        onCancel={() => setCancelling(true)}
      />
      {cancelling && (
        <CancelSheet
          busy={cancel.isPending}
          onClose={() => setCancelling(false)}
          onPick={cancelPick}
        />
      )}
    </section>
  );
}

/** 409 отмены: «Работа выполнена» уже отмечена (MU-8). */
const MARKED_DONE = 'deal_marked_done';

/** Чат сделки: открыть (`conversation_id`) или начать по отклику — тот же диалог, что у
 *  «Написать» на S24. `share` — сразу шторка S54 «Поделиться контактом». */
function useDealChat(deal: DealCardOut) {
  const router = useRouter();
  const start = useStartConversation();
  const open = (id: string, share: boolean) =>
    void router.navigate({ to: chatPath(id), search: share ? { share: true } : {} });
  const go = (share: boolean) => {
    if (deal.conversation_id) open(deal.conversation_id, share);
    else if (deal.response_id)
      start.mutate({ response_id: deal.response_id }, { onSuccess: (s) => open(s.id, share) });
  };
  return {
    available: Boolean(deal.conversation_id ?? deal.response_id),
    write: () => go(false),
    share: () => go(true),
    pending: start.isPending,
    error: start.error,
  };
}

/** Строки внизу (UX_GUIDANCE №2, §5): «Работа уже сделана? Отметить», пока её час не настал;
 *  «Есть проблема» (спор S52; под спором — «Спор по сделке», после решения — «Решение по
 *  спору») — строкой, а не нативной кнопкой с первой минуты; «Отменить сделку» — пока никто не
 *  отметил «Работа выполнена» (MU-8). */
function Actions({
  deal,
  early,
  onMark,
  cancellable,
  onCancel,
}: {
  deal: DealCardOut;
  early: boolean;
  onMark: () => void;
  cancellable: boolean;
  onCancel: () => void;
}) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const client = deal.my_role === 'client';
  const resolved = deal.dispute?.status === 'resolved';
  const problem =
    deal.status === 'disputed'
      ? t('deal.disputeLink')
      : resolved
        ? t('deal.disputeResult')
        : deal.status === 'agreed'
          ? t('deal.problem')
          : null;
  if (!early && !problem && !cancellable) return null;
  return (
    <Group>
      {early && <Row icon="check" title={t('deal.markEarly')} onClick={onMark} />}
      {problem && (
        <Row
          icon="flag"
          title={problem}
          chevron
          onClick={() => void router.navigate({ to: disputePath(deal.id) })}
        />
      )}
      {cancellable && (
        <Row
          danger
          title={t('deal.cancel')}
          subtitle={client ? t('deal.cancelHintClient') : t('deal.cancelHintPerformer')}
          icon="x"
          onClick={onCancel}
        />
      )}
    </Group>
  );
}

/** Памятка о предоплате — одной строкой, а не баннером: за путь клиент видит её уже не раз
 *  (UX_GUIDANCE §5); формулировка прежняя. */
function SafetyLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 flex items-start gap-1.5 px-1 text-cap text-text2">
      <Icon name="alert" size={16} className="mt-px shrink-0 text-urgent-soft-ink" />
      {children}
    </p>
  );
}

/** Название и статус, «сегодня в 19:00 · 3 500 RSD»; у идущей сделки без отметок — одной строкой,
 *  что дальше: «Исполнителю пришло уведомление. Договоритесь о времени и адресе в чате.» (№2). */
function Header({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const offerPrice = useOfferPrice();
  const when = deal.scheduled_at
    ? format.calendar(new Date(deal.scheduled_at))
    : deal.availability_note;
  const price =
    deal.price.type === null || deal.price.type === 'negotiable'
      ? t('card.negotiable')
      : offerPrice({ type: deal.price.type, amount: deal.price.amount });
  const { timeline } = deal;
  // отметки «Работа выполнена» объясняет State; из чата («Договориться») — без «выбрал вас»
  const next =
    deal.status !== 'agreed' || timeline.my_mark_at !== null || timeline.other_mark_at !== null
      ? null
      : deal.origin === 'job_response'
        ? deal.my_role
        : 'chat';
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start justify-between gap-3">
        <Heading variant="h2" as="h1">
          {deal.title}
        </Heading>
        <Badge tone={STATUS_TONE[deal.status]}>{t(`deal.status.${deal.status}`)}</Badge>
      </div>
      <p className="m-0 flex flex-wrap items-center gap-1.5">
        {when && (
          <>
            <span className="text-text2">{when}</span>
            <span className="text-text2" aria-hidden="true">
              ·
            </span>
          </>
        )}
        <Price>{price}</Price>
      </p>
      {next && (
        <Text variant="sm" secondary className="pt-1">
          {t(`deal.next.${next}`)}
        </Text>
      )}
    </div>
  );
}

/** Вторая сторона: фото, имя, рейтинг и роль; профиль специалиста — ссылкой на S08. */
function Counterpart({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const party = deal.counterpart;
  const name = party.display_name || t('deal.deletedParty');
  const avatar =
    party.avatar?.variants.find((v) => v.name === 'thumb') ?? party.avatar?.variants[0];
  const role = t(`deal.role.${party.role}`);
  const profile = party.profile_id;
  return (
    <Card
      tight
      aria-label={t(`deal.role.${party.role}`)}
      href={profile ? router.history.createHref(specialistPath(profile)) : undefined}
      onClick={
        profile
          ? (event) => {
              event.preventDefault();
              void router.navigate({ to: specialistPath(profile) });
            }
          : undefined
      }
    >
      <div className="flex items-center gap-3">
        <Avatar name={name} src={avatar?.url} placeholder={party.avatar?.placeholder} />
        <div className="flex min-w-0 grow flex-col gap-0.5">
          <span className="text-title">{name}</span>
          {/* рейтинг — у исполнителя; у клиента — только роль */}
          {party.role === 'performer' ? (
            <PerformerRating rating={party.rating} count={party.rating_count} meta={[role]} />
          ) : (
            <Text as="span" variant="cap">
              {role}
            </Text>
          )}
        </div>
        {profile && <Icon name="chev-right" className="shrink-0 text-text2" />}
      </div>
      {party.phone_verified && (
        <div className="flex">
          <Badge tone="info" icon="shield">
            {t('manage.phone')}
          </Badge>
        </div>
      )}
    </Card>
  );
}

/** После договорённости — как связаться: «Написать» (когда главная кнопка занята «Работа
 *  выполнена»), Telegram второй стороны (если показывает) и «Поделиться контактом» — шторка S54 в
 *  чате сделки; у выполненной сделки делиться уже нечем (№13). */
function Contacts({
  deal,
  chat,
  write,
}: {
  deal: DealCardOut;
  chat: ReturnType<typeof useDealChat>;
  write: boolean;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const username = deal.counterpart.telegram;
  const writable = write && chat.available;
  const share = chat.available && deal.status !== 'completed';
  if (!writable && !username && !share) return null;
  return (
    <section className="flex flex-col gap-2" aria-label={t('deal.contacts.title')}>
      <Group>
        {writable && (
          <Row icon="chat" title={common('action.write')} chevron onClick={chat.write} />
        )}
        {username && (
          <Row
            icon="send"
            title={t('deal.contacts.telegram', { username })}
            chevron
            onClick={() => platform.openTelegramLink(`https://t.me/${username.replace(/^@/, '')}`)}
          />
        )}
        {share && (
          <Row
            icon="phone"
            title={t('deal.contacts.share')}
            subtitle={t('deal.contacts.shareHint')}
            chevron
            onClick={chat.share}
          />
        )}
      </Group>
    </section>
  );
}

/** «Заказать снова» клиенту завершённой сделки: прямой диалог с этим специалистом (уже начатый —
 *  тот же), как «Написать» на S08; договариваются там — «Договориться» в шапке S30. */
function OrderAgain({ profileId }: { profileId: string }) {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  const start = useStartConversation();
  const order = () =>
    start.mutate(
      { profile_id: profileId },
      { onSuccess: (started) => void router.navigate({ to: chatPath(started.id) }) },
    );
  return (
    <>
      <Button
        variant="secondary"
        full
        disabled={start.isPending}
        aria-busy={start.isPending}
        onClick={order}
      >
        {t('deal.orderAgain')}
      </Button>
      {start.error && <ActionError error={start.error} fallback={t('deal.orderAgainError')} />}
    </>
  );
}

/** Адрес — сторонам; копировать одной кнопкой. Без адреса — только район. */
function Address({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const [copied, setCopied] = useState(false);
  const { place } = deal;
  const district = place.district?.name ?? place.city?.name ?? null;
  if (!place.address && !district) return null;
  const name = deal.counterpart.display_name || t('deal.deletedParty');
  const hint = place.address
    ? district
      ? t('deal.addressHintDistrict', { district, name })
      : t('deal.addressHint', { name })
    : t(deal.my_role === 'client' ? 'deal.noAddress' : 'deal.noAddressPerformer');
  const canCopy = Boolean(place.address) && typeof navigator !== 'undefined' && navigator.clipboard;
  return (
    <Card tight as="section" aria-label={place.address ?? district ?? undefined}>
      <div className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-bg text-text2">
          <Icon name="pin" />
        </span>
        <span className="flex min-w-0 grow flex-col gap-0.5">
          <span className="font-semibold">{place.address ?? district}</span>
          <Text as="span" variant="cap">
            {copied ? t('deal.copied') : hint}
          </Text>
        </span>
        {canCopy && (
          <IconButton
            icon="copy"
            label={t('deal.copy')}
            onClick={() => {
              void navigator.clipboard.writeText(place.address ?? '').then(() => setCopied(true));
            }}
          />
        )}
      </div>
    </Card>
  );
}

/** «Статус»: вехи сделки таймлайном — текущая и следующая, пройденные и дальние — под
 *  «Подробнее» (UX_GUIDANCE §5). «Отзыв» — шаг клиента: исполнитель отзыв не пишет, и шаг не
 *  висел у него текущим вечно (№13). */
function Steps({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const id = useId();
  const [all, setAll] = useState(false);
  const { timeline } = deal;
  const stamp = (value: string) => {
    const date = new Date(value);
    return new Date().toDateString() === date.toDateString()
      ? format.time(date)
      : format.date(date);
  };
  const done = deal.status === 'completed';
  const work = deal.scheduled_at
    ? t('deal.step.workAt', { time: format.calendarGenitive(new Date(deal.scheduled_at)) })
    : (deal.availability_note ?? undefined);
  const items: TimelineItem[] = [];
  if (timeline.responded_at) {
    items.push({
      key: 'responded',
      title: t('deal.step.responded'),
      meta: stamp(timeline.responded_at),
      state: 'done',
    });
  }
  items.push(
    {
      key: 'chosen',
      title: t('deal.step.chosen'),
      meta: timeline.agreed_at ? stamp(timeline.agreed_at) : undefined,
      state: timeline.agreed_at ? 'done' : 'now',
    },
    {
      key: 'agreed',
      title: t('deal.step.agreed'),
      meta: work,
      state: done
        ? 'done'
        : deal.status === 'agreed' || deal.status === 'disputed'
          ? 'now'
          : 'next',
    },
    {
      key: 'done',
      title: t('deal.step.done'),
      meta: timeline.completed_at ? stamp(timeline.completed_at) : undefined,
      state: done ? 'done' : 'next',
    },
  );
  if (deal.my_role === 'client') {
    items.push({
      key: 'review',
      title: t('deal.step.review'),
      state: deal.my_review ? 'done' : done ? 'now' : 'next',
    });
  }
  const now = items.findIndex((item) => item.state === 'now');
  const shown = all || now < 0 ? items : items.slice(now, now + 2);
  return (
    <Card tight as="section" aria-labelledby={id}>
      <Heading variant="h3" as="h2" id={id}>
        {t('deal.statusTitle')}
      </Heading>
      <Timeline items={shown} />
      {(all || shown.length < items.length) && (
        <LinkButton
          aria-expanded={all}
          onClick={() => setAll(!all)}
          className="-my-1 -ml-2 self-start"
        >
          {t(all ? 'deal.stepsLess' : 'deal.stepsMore')}
        </LinkButton>
      )}
    </Card>
  );
}

/** Что сейчас: отметки «Работа выполнена», завершение или отмена с причиной. */
function State({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const { timeline } = deal;
  if (deal.status === 'completed' && timeline.completed_at) {
    const review = deal.my_review;
    return (
      <>
        <Banner tone="ok" role="status">
          {t('deal.completed', { date: format.dateGenitive(new Date(timeline.completed_at)) })}
        </Banner>
        {review && (
          <Banner tone={review.status === 'removed' ? 'warn' : 'info'} icon="star">
            {t(`deal.myReview.${review.status as ReviewState}`)}
          </Banner>
        )}
        {!review && deal.review_until && (
          <Banner tone="info" icon="star">
            {t('deal.reviewUntil', { date: format.dateGenitive(new Date(deal.review_until)) })}
          </Banner>
        )}
      </>
    );
  }
  if (deal.status === 'cancelled') {
    const reason = deal.cancel_reason;
    const text =
      reason === 'expired'
        ? t('deal.cancelledExpired')
        : reason === 'account_deleted'
          ? t('deal.cancelledDeleted')
          : reason === 'dispute'
            ? t('deal.cancelledDispute')
            : t(deal.cancelled_by_me ? 'deal.cancelledByMe' : 'deal.cancelledByOther', {
                reason: t(`deal.reason.${partyReason(reason)}`),
              });
    return (
      <Banner tone="info" role="status">
        {text}
      </Banner>
    );
  }
  if (deal.status === 'disputed') {
    return (
      <Banner tone="warn" role="status">
        {t('deal.disputeOpen')}
      </Banner>
    );
  }
  if (deal.status !== 'agreed') return null;
  if (timeline.my_mark_at) {
    return (
      <Banner tone="ok" role="status">
        {t('deal.marked')}
      </Banner>
    );
  }
  if (timeline.other_mark_at) {
    return (
      <Banner tone="info" role="status">
        {t('deal.otherMarked')}
      </Banner>
    );
  }
  return null;
}

function partyReason(reason: DealCardOut['cancel_reason']): PartyReason {
  return reason !== null && PARTY_REASONS.has(reason) ? (reason as PartyReason) : 'other';
}

function CancelSheet({
  onClose,
  onPick,
  busy,
}: {
  onClose: () => void;
  onPick: (reason: PartyReason) => void;
  busy: boolean;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  useBackButton(onClose);
  return (
    <Sheet open title={t('deal.cancelTitle')} onClose={onClose} closeLabel={common('action.close')}>
      <div className="flex flex-col gap-2">
        {REASONS.map((reason) => (
          <Button
            key={reason}
            variant="outline"
            full
            disabled={busy}
            onClick={() => onPick(reason)}
          >
            {t(`deal.reasonOption.${reason}`)}
          </Button>
        ))}
      </div>
    </Sheet>
  );
}

function Gone() {
  const { t } = useTranslation('jobs');
  const router = useRouter();
  return (
    <section className="px-4 pt-6">
      <EmptyState as="h1" icon="ban" title={t('deal.unavailable')}>
        <Text variant="sm">{t('deal.unavailableText')}</Text>
        <Button
          variant="secondary"
          onClick={() => void router.navigate({ to: JOBS_PATHS.mine, replace: true })}
        >
          {t('segments.mine')}
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
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6" aria-busy="true">
      {/* шапка на фоне экрана: название и статус, цена */}
      <div className="flex flex-col gap-1">
        <div className="flex items-start justify-between gap-3">
          <SkeletonText size="h2" screen className="w-3/5" />
          <Skeleton screen className="h-6 w-24" />
        </div>
        <SkeletonText size="sm" screen className="w-1/2" />
      </div>
      {/* вторая сторона */}
      <SkeletonCard>
        <div className="flex items-center gap-3">
          <Skeleton round className="size-12 shrink-0" />
          <div className="flex min-w-0 grow flex-col">
            <SkeletonText size="title" className="w-2/5" />
            <SkeletonText size="cap" className="w-1/3" />
          </div>
        </div>
      </SkeletonCard>
      {/* место и шаги сделки */}
      <SkeletonCard tight>
        <SkeletonText size="h3" className="w-1/4" />
        <SkeletonText size="sm" className="w-3/5" />
      </SkeletonCard>
      <SkeletonCard>
        {[0, 1, 2].map((step) => (
          <div key={step} className="flex items-center gap-3">
            <Skeleton round className="size-6 shrink-0" />
            <SkeletonText size="sm" className={step === 1 ? 'w-2/5' : 'w-1/2'} />
          </div>
        ))}
      </SkeletonCard>
    </section>
  );
}
