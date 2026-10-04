// S56 «Отзыв о прошлой работе» (DEVELOPMENT_PLAN 7.6а): прошлый клиент по ссылке специалиста
// (`ri_`, S55) — кто просит отзыв (фото, имя, «коротко о себе», категории), звёзды с подписью,
// «Что делал мастер», текст и галочка «Подтверждаю: … делал(а) для меня эту работу»; MainButton
// «Отправить отзыв» — после оценки. Отзыв ждёт модератора, на карточке он с пометкой «До платформы»
// и в рейтинг не входит. Ссылка отозвана, истекла, использована или её нет — один нейтральный экран
// без подробностей (backend отвечает одинаковым 404); свою ссылку специалисту заполнять нельзя
// (`is_own`); второй отзыв о том же специалисте — объяснение. Отправить может только вошедший:
// гостю — «Откройте ссылку в Telegram»; без согласия с правилами — S02c (routes/guards.ts).
import type { InviteReviewIn, InviteSpecialistOut } from '@sosed/api-client';
import { ApiError, getSession } from '@sosed/api-client';
import {
  INVITE_BODY_MAX,
  INVITE_WORK_MAX,
  isUnavailable,
  systemStateOf,
  useLeaveInviteReview,
  useReviewInvite,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  FieldSkeleton,
  Heading,
  Input,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  Stars,
  Text,
  Textarea,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { HOME_PATH, jobIdOf } from '../shared/paths.ts';

type Grade = 1 | 2 | 3 | 4 | 5;
/** Аватар специалиста в шапке — 48 px, как .ava артборда. */
const AVATAR_PX = 48;
/** Почему форма закрыта: ссылка недействительна, своя ссылка, отзыв уже оставлен. */
type Closed = 'invalid' | 'own' | 'exists';

export function InviteReviewScreen() {
  const { token: raw = '' } = useParams({ strict: false });
  const token = jobIdOf(raw);
  const router = useRouter();
  const signedIn = getSession() !== null;
  const form = useReviewInvite(signedIn ? token : null);
  // ответ на отправку: «Спасибо» или почему отзыв не принят — экран остаётся на нём
  const [outcome, setOutcome] = useState<'sent' | Closed | null>(null);
  const home = () => void router.navigate({ to: HOME_PATH, replace: true });
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else home();
  });

  if (!signedIn) return <Notice closed="signedOut" onHome={home} />;
  if (outcome === 'sent') return <Sent onHome={home} />;
  if (outcome) return <Notice closed={outcome} onHome={home} />;
  if (token === null || (form.isError && isUnavailable(form.error))) {
    return <Notice closed="invalid" onHome={home} />;
  }
  if (form.isError) {
    return (
      <section className="px-4 pt-6">
        <LoadError
          error={form.error}
          onRetry={() => void form.refetch()}
          retrying={form.isRefetching}
        />
      </section>
    );
  }
  if (!form.data) return <Loading />;
  if (form.data.is_own) return <Notice closed="own" onHome={home} />;
  return <Form token={token} specialist={form.data.specialist} onDone={setOutcome} />;
}

/** Код ошибки отправки, после которой форма больше не нужна. */
function closedBy(error: unknown): Closed | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 404) return 'invalid';
  if (error.problem.code === 'own_profile_review') return 'own';
  if (error.problem.code === 'pre_platform_review_exists') return 'exists';
  return null;
}

function Form({
  token,
  specialist,
  onDone,
}: {
  token: string;
  specialist: InviteSpecialistOut;
  onDone: (outcome: 'sent' | Closed) => void;
}) {
  const { t } = useTranslation('jobs');
  const leave = useLeaveInviteReview(token);
  const [rating, setRating] = useState(0);
  const [work, setWork] = useState('');
  const [body, setBody] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [checked, setChecked] = useState(false);
  const missingId = useId();
  const name = specialist.first_name || specialist.display_name;
  const missing = checked && !confirmed;
  const submit = () => {
    setChecked(true);
    if (!confirmed || rating === 0 || leave.isPending) return;
    const review: InviteReviewIn = {
      rating,
      work_title: work.trim() || null,
      body: body.trim() || null,
      confirmed: true,
    };
    leave.mutate(review, {
      onSuccess: () => onDone('sent'),
      onError: (error) => {
        const closed = closedBy(error);
        if (closed) onDone(closed);
      },
    });
  };
  useStepButton({
    text: t('inviteReview.submit'),
    visible: true,
    enabled: rating > 0,
    loading: leave.isPending,
    onClick: submit,
  });
  const offline = leave.error ? systemStateOf(leave.error).kind === 'offline' : false;
  const detail =
    leave.error instanceof ApiError && leave.error.status < 500 ? leave.error.problem.detail : null;

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        {/* заголовок внутреннего экрана — .h2, как на артборде */}
        <Heading variant="h2" as="h1">
          {t('inviteReview.title')}
        </Heading>
        <Text variant="sm" secondary>
          {t('inviteReview.lead', { name })}
        </Text>
      </div>
      <SpecialistHeader specialist={specialist} />
      <div className="flex flex-col gap-1">
        {/* видимая подпись, как .lbl артборда; группе звёзд имя даёт `label` */}
        <span aria-hidden="true" className="text-sm font-semibold">
          {t('review.rating')}
        </span>
        <Stars
          value={rating}
          onChange={setRating}
          label={t('review.rating')}
          starLabel={(count) => t('review.star', { count })}
        />
        {/* подпись оценки («Отлично») — строкой .cap; место под неё есть и до выбора */}
        <p aria-live="polite" className="m-0 min-h-4.5 text-cap text-text2">
          {rating > 0 ? t(`review.grade.${rating as Grade}`) : null}
        </p>
      </div>
      <Field label={t('inviteReview.work')}>
        <Input
          value={work}
          maxLength={INVITE_WORK_MAX}
          placeholder={t('inviteReview.workPlaceholder')}
          onChange={(event) => setWork(event.target.value)}
        />
      </Field>
      <Field label={t('review.body')} hint={t('review.hint')}>
        <Textarea
          value={body}
          maxLength={INVITE_BODY_MAX}
          placeholder={t('inviteReview.placeholder')}
          onChange={(event) => setBody(event.target.value)}
        />
      </Field>
      <div className="flex flex-col gap-1.5">
        <Checkbox
          checked={confirmed}
          onChange={setConfirmed}
          invalid={missing}
          describedBy={missing ? missingId : undefined}
          className="text-sm"
        >
          {t('inviteReview.confirm', { name })}
        </Checkbox>
        {missing && (
          <p id={missingId} role="alert" className="m-0 pl-8.5 text-cap text-danger">
            {t('inviteReview.confirmMissing')}
          </p>
        )}
      </div>
      <Banner tone="info">{t('inviteReview.note')}</Banner>
      {leave.error && !closedBy(leave.error) && (
        <Banner tone="danger" role="alert" icon={offline ? 'wifi-off' : 'alert'}>
          {detail ?? t('review.failed')}
        </Banner>
      )}
    </section>
  );
}

/** Кто просит отзыв: фото или инициалы, имя, «коротко о себе» и категории. */
function SpecialistHeader({ specialist }: { specialist: InviteSpecialistOut }) {
  const categories = specialist.categories.map((category) => category.name).join(' · ');
  return (
    <Card className="flex-row items-center">
      <Avatar
        name={specialist.display_name}
        src={avatarSrc(specialist)}
        placeholder={specialist.avatar?.placeholder}
      />
      <div className="flex min-w-0 grow flex-col">
        <span className="text-title">{specialist.display_name}</span>
        {specialist.headline && (
          <Text variant="sm" secondary>
            {specialist.headline}
          </Text>
        )}
        {categories && <Text variant="cap">{categories}</Text>}
      </div>
    </Card>
  );
}

/** Самый маленький вариант фото, которого хватит аватару на экране плотностью 3x. */
function avatarSrc({ avatar }: InviteSpecialistOut): string | undefined {
  if (!avatar) return undefined;
  const sorted = [...avatar.variants].sort((a, b) => a.width - b.width);
  return (sorted.find((variant) => variant.width >= AVATAR_PX * 3) ?? sorted.at(-1))?.url;
}

function Sent({ onHome }: { onHome: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="flex flex-col gap-4 px-4 pt-10 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="accent"
        icon="check"
        title={t('inviteReview.sent')}
        action={
          <Button variant="secondary" onClick={onHome}>
            {t('inviteReview.home')}
          </Button>
        }
      >
        {t('inviteReview.sentText')}
      </EmptyState>
    </section>
  );
}

const NOTICE_ICON = { invalid: 'link', own: 'user', exists: 'star', signedOut: 'lock' } as const;

/** Форма не нужна: ссылка недействительна, своя ссылка, отзыв уже есть или нет входа. */
function Notice({ closed, onHome }: { closed: Closed | 'signedOut'; onHome: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="flex flex-col px-4 pt-10 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="neutral"
        icon={NOTICE_ICON[closed]}
        title={t(`inviteReview.${closed}`)}
        action={
          closed === 'signedOut' ? undefined : (
            <Button variant="secondary" onClick={onHome}>
              {t('inviteReview.home')}
            </Button>
          )
        }
      >
        {t(`inviteReview.${closed}Text`)}
      </EmptyState>
    </section>
  );
}

function Loading() {
  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6" aria-busy="true">
      <div className="flex flex-col gap-1">
        <SkeletonText size="h2" screen className="w-2/3" />
        <SkeletonText size="sm" screen className="w-full" />
      </div>
      {/* кто просит отзыв */}
      <SkeletonCard>
        <div className="flex items-center gap-3">
          <Skeleton round className="size-12 shrink-0" />
          <div className="flex min-w-0 grow flex-col gap-0.5">
            <SkeletonText size="title" className="w-2/5" />
            <SkeletonText size="sm" className="w-3/5" />
          </div>
        </div>
      </SkeletonCard>
      {/* звёзды и поля */}
      <Skeleton screen className="h-9 w-48" />
      <FieldSkeleton />
      <FieldSkeleton tall />
    </section>
  );
}
