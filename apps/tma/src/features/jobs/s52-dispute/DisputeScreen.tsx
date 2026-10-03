// S52 «Проблема со сделкой» (DEVELOPMENT_PLAN 6.1c, 6.2): спор по идущей сделке. Вход — «Есть
// проблема» S26, «Есть проблема» под «Работа выполнена?» в боте и «Ответить» уведомления о споре
// (deep link `p_` — сразу сюда, без S26). Данные — карточка сделки (BFF), в ней последний спор.
// - Спора нет (или прежний отозван), сделка идёт — форма по артборду: «Что случилось?» (пять
//   вариантов строками группы), «Опишите, что произошло», фото и скриншоты (media `dispute`,
//   приватный бакет), памятка «… получит уведомление и 48 часов на ответ»; MainButton «Отправить».
// - Спор идёт — статус («Ждём ответа», «Есть ответ», «Нет ответа»), что сообщили и фото, ответ
//   второй стороны. Второй стороне — срок и форма ответа (MainButton «Ответить»; после 48 ч тоже
//   можно), открывшему — «Отозвать спор» с подтверждением: сделка снова идёт.
// - Решён — решение поддержки и причина (statement of reasons), «К сделке».
// - Сделка не идёт и спора не было — объяснение и «К сделке».
// Ответ сервера на «Отправить», «Ответить» и «Отозвать» — спор: он сразу в карточке сделки.
import type {
  DealCardDisputeOut,
  DealCardDisputePhotoOut,
  DealCardOut,
  DisputeKind,
} from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import type { UploadItem } from '@sosed/hooks';
import {
  isUnavailable,
  useDealCard,
  useMediaUploads,
  useOpenDispute,
  useRespondDispute,
  useWithdrawDispute,
} from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import {
  AddTile,
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Field,
  FieldSkeleton,
  Group,
  Heading,
  IconButton,
  Photo,
  RadioGroup,
  RadioRow,
  Row,
  RowsSkeleton,
  Sheet,
  Skeleton,
  SkeletonText,
  Text,
  Textarea,
  UploadTile,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import { useId, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { dealPath, jobIdOf } from '../shared/paths.ts';
import { mediaTransport } from '../shared/uploads.ts';

/** Варианты артборда по порядку; «Ущерб имуществу» (`damage`) — только в API. */
const KINDS: readonly DisputeKind[] = ['no_show', 'quality', 'prepayment_taken', 'safety', 'other'];
/** Как у backend (domain/dispute.py): текст и фото каждой стороны. */
const MAX_TEXT = 2000;
const MAX_PHOTOS = 6;
const PHOTO_TILE = 'size-16';
const STATUS_TONE = {
  open: 'urgent',
  answered: 'info',
  no_response: 'urgent',
  resolved: 'ok',
  withdrawn: 'mute',
} as const;
/** Коды причин решения с текстом; остальные — «решение по материалам спора». */
const REASONS = new Set([
  'work_done',
  'not_done',
  'no_show',
  'poor_quality',
  'prepayment_scam',
  'no_response',
  'mutual',
]);
type Reason =
  | 'work_done'
  | 'not_done'
  | 'no_show'
  | 'poor_quality'
  | 'prepayment_scam'
  | 'no_response'
  | 'mutual'
  | 'other';

export function DisputeScreen() {
  const { dealId: raw = '' } = useParams({ strict: false });
  const dealId = jobIdOf(raw);
  const router = useRouter();
  const card = useDealCard(dealId);
  const toDeal = () => void router.navigate({ to: dealPath(raw), replace: true });
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else toDeal();
  });

  if (dealId === null || (card.isError && isUnavailable(card.error))) {
    return <Closed gone onDeal={toDeal} />;
  }
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
  const deal = card.data;
  const dispute = deal.dispute?.status === 'withdrawn' ? null : deal.dispute;
  if (dispute) return <Dispute deal={deal} dispute={dispute} onDeal={toDeal} />;
  if (deal.status !== 'agreed') return <Closed gone={false} onDeal={toDeal} />;
  return <Form deal={deal} />;
}

/** «Проблема со сделкой», статус спора и строка сделки: «Повесить люстру · Алексей Морозов ·
 *  сегодня, 19:00». Второй стороне спор, ждущий ответа, — «Нужен ваш ответ». */
function Header({ deal, dispute }: { deal: DealCardOut; dispute?: DealCardDisputeOut }) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const when = deal.scheduled_at
    ? format.calendar(new Date(deal.scheduled_at))
    : deal.availability_note;
  const line = [deal.title, deal.counterpart.display_name || null, when].filter(Boolean);
  const yours = dispute?.status === 'open' && !dispute.opened_by_me;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start justify-between gap-3">
        <Heading variant="h2" as="h1">
          {t('dispute.title')}
        </Heading>
        {dispute && (
          <Badge tone={STATUS_TONE[dispute.status]}>
            {yours ? t('dispute.status.yours') : t(`dispute.status.${dispute.status}`)}
          </Badge>
        )}
      </div>
      <Text variant="cap">{line.join(' · ')}</Text>
    </div>
  );
}

function Form({ deal }: { deal: DealCardOut }) {
  const { t } = useTranslation('jobs');
  const whatId = useId();
  const open = useOpenDispute(deal.id);
  const photos = useEvidence();
  const [kind, setKind] = useState<DisputeKind | null>(null);
  const [description, setDescription] = useState('');
  const name = deal.counterpart.display_name;
  const ready = kind !== null && description.trim() !== '' && !photos.uploads.uploading;
  useStepButton({
    text: t('dispute.send'),
    visible: true,
    enabled: ready,
    loading: open.isPending,
    onClick: () => {
      if (kind === null) return;
      open.mutate({
        kind,
        description: description.trim(),
        media_ids: [...photos.uploads.mediaIds],
      });
    },
  });

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-4 pb-6">
      <Header deal={deal} />
      <div className="flex flex-col gap-2">
        <h2 id={whatId} className="m-0 text-sm font-semibold">
          {t('dispute.what')}
        </h2>
        <RadioGroup labelledBy={whatId}>
          <Group>
            {KINDS.map((value) => (
              <RadioRow
                key={value}
                title={t(`dispute.kind.${value}`)}
                checked={kind === value}
                onChange={() => setKind(value)}
              />
            ))}
          </Group>
        </RadioGroup>
      </div>
      <Field label={t('dispute.describe')}>
        <Textarea
          value={description}
          maxLength={MAX_TEXT}
          placeholder={t('dispute.describePlaceholder')}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <EvidenceField photos={photos} hint={t('dispute.photoHint')} />
      <Banner tone="info" icon="clock">
        {name ? t('dispute.notice', { name }) : t('dispute.noticeNoName')}
      </Banner>
      {open.error && <ActionError error={open.error} fallback={t('dispute.sendError')} />}
    </section>
  );
}

function Dispute({
  deal,
  dispute,
  onDeal,
}: {
  deal: DealCardOut;
  dispute: DealCardDisputeOut;
  onDeal: () => void;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const respond = useRespondDispute(deal.id);
  const withdraw = useWithdrawDispute(deal.id);
  const photos = useEvidence();
  const [answer, setAnswer] = useState('');
  const [confirming, setConfirming] = useState(false);
  const active = dispute.status !== 'resolved';
  const answering =
    !dispute.opened_by_me && (dispute.status === 'open' || dispute.status === 'no_response');
  const until = format.calendar(new Date(dispute.respond_by));
  const name = deal.counterpart.display_name;
  useStepButton({
    text: t('dispute.answer'),
    visible: answering,
    enabled: answer.trim() !== '' && !photos.uploads.uploading,
    loading: respond.isPending,
    onClick: () => respond.mutate({ text: answer.trim(), media_ids: [...photos.uploads.mediaIds] }),
  });

  return (
    <section className="flex flex-col gap-3 px-4 pt-4 pb-6">
      <Header deal={deal} dispute={dispute} />
      <Message
        title={dispute.opened_by_me ? t('dispute.mine') : t('dispute.theirs')}
        kind={dispute.kind}
        text={dispute.description}
        photos={dispute.photos}
        at={dispute.created_at}
      />
      {dispute.response !== null && (
        <Message
          title={dispute.opened_by_me ? t('dispute.response') : t('dispute.myResponse')}
          text={dispute.response}
          photos={dispute.response_photos}
          at={dispute.responded_at}
        />
      )}
      <State dispute={dispute} name={name} until={until} />
      {answering && (
        <>
          <Field label={t('dispute.answerLabel')}>
            <Textarea
              value={answer}
              maxLength={MAX_TEXT}
              placeholder={t('dispute.answerPlaceholder')}
              onChange={(event) => setAnswer(event.target.value)}
            />
          </Field>
          <EvidenceField photos={photos} hint={t('dispute.photoHint')} />
        </>
      )}
      {respond.error && <ActionError error={respond.error} fallback={t('dispute.answerError')} />}
      {withdraw.error && (
        <ActionError error={withdraw.error} fallback={t('dispute.withdrawError')} />
      )}
      {active && dispute.opened_by_me && (
        <Group>
          <Row
            title={<span className="text-danger">{t('dispute.withdraw')}</span>}
            subtitle={t('dispute.withdrawHint')}
            icon="x"
            onClick={() => setConfirming(true)}
          />
        </Group>
      )}
      {!active && (
        <Button variant="secondary" full onClick={onDeal}>
          {t('dispute.toDeal')}
        </Button>
      )}
      {confirming && (
        <WithdrawSheet
          busy={withdraw.isPending}
          onClose={() => setConfirming(false)}
          onConfirm={() =>
            withdraw.mutate(undefined, {
              onSettled: () => setConfirming(false),
              onSuccess: onDeal,
            })
          }
        />
      )}
    </section>
  );
}

/** Что сейчас: ждём ответа, ответьте до, нет ответа, решение поддержки. */
function State({
  dispute,
  name,
  until,
}: {
  dispute: DealCardDisputeOut;
  name: string;
  until: string;
}) {
  const { t } = useTranslation('jobs');
  if (dispute.status === 'resolved' && dispute.outcome) {
    const code = dispute.reason_code ?? 'other';
    const reason = t(`dispute.reason.${(REASONS.has(code) ? code : 'other') as Reason}`);
    return (
      <Banner tone="ok" role="status">
        {t(`dispute.resolved.${dispute.outcome}`)} {t('dispute.reasonLine', { reason })}
      </Banner>
    );
  }
  if (dispute.status === 'answered') {
    return (
      <Banner tone="info" icon="clock" role="status">
        {t('dispute.inReview')}
      </Banner>
    );
  }
  if (dispute.status === 'no_response') {
    return (
      <Banner tone="warn" role="status">
        {dispute.opened_by_me ? t('dispute.noResponse') : t('dispute.noResponseLate')}
      </Banner>
    );
  }
  if (!dispute.opened_by_me) {
    return (
      <Banner tone="warn" icon="clock" role="status">
        {t('dispute.answerUntil', { date: until })}
      </Banner>
    );
  }
  return (
    <Banner tone="info" icon="clock" role="status">
      {name
        ? t('dispute.waiting', { name, date: until })
        : t('dispute.waitingNoName', { date: until })}
    </Banner>
  );
}

/** Сообщение стороны: что случилось (у открывшего), текст, фото и когда. */
function Message({
  title,
  kind,
  text,
  photos,
  at,
}: {
  title: string;
  kind?: DisputeKind;
  text: string;
  photos: readonly DealCardDisputePhotoOut[];
  at: string | null;
}) {
  const { t } = useTranslation('jobs');
  const format = useFormat();
  const id = useId();
  return (
    <Card tight as="section" aria-labelledby={id}>
      <Heading variant="h3" as="h2" id={id}>
        {title}
      </Heading>
      {kind && <span className="font-semibold">{t(`dispute.kind.${kind}`)}</span>}
      <Text variant="sm" className="whitespace-pre-line">
        {text}
      </Text>
      {photos.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label={t('dispute.photos')}>
          {photos.map((photo, index) => (
            <li key={photo.id}>
              <Photo
                variants={photo.variants}
                placeholder={photo.placeholder}
                sizes="64px"
                alt={t('dispute.photoNumber', { number: index + 1 })}
                className={PHOTO_TILE}
              />
            </li>
          ))}
        </ul>
      )}
      {at && (
        <Text variant="cap" secondary>
          {t('dispute.sentAt', { date: format.calendar(new Date(at)) })}
        </Text>
      )}
    </Card>
  );
}

interface Evidence {
  uploads: ReturnType<typeof useMediaUploads>;
  add: (files: File[]) => void;
}

/** Фото-доказательства формы: назначение `dispute`, не больше шести. */
function useEvidence(): Evidence {
  const platform = usePlatform();
  const uploads = useMediaUploads({
    purpose: 'dispute',
    transport: mediaTransport,
    max: MAX_PHOTOS,
  });
  return {
    uploads,
    add: (files) => {
      const left = uploads.add(files);
      if (left > 0) platform.haptics.notification('warning');
      else platform.haptics.selection();
    },
  };
}

/** Плитки фото и «Фото» с подсказкой рядом, как на артборде. */
function EvidenceField({ photos, hint }: { photos: Evidence; hint: string }) {
  const { t } = useTranslation('jobs');
  const { items } = photos.uploads;
  return (
    <div className="flex flex-col gap-2">
      {items.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {items.map((item, index) => (
            <EvidenceTile key={item.key} item={item} index={index} photos={photos} />
          ))}
        </div>
      )}
      <div className="flex items-center gap-3">
        {items.length < MAX_PHOTOS && (
          <AddTile
            label={t('dispute.photo')}
            icon="camera"
            accept="image/*"
            multiple
            onFiles={photos.add}
            className={PHOTO_TILE}
          />
        )}
        <Text as="span" variant="cap" className="min-w-0 grow">
          {hint}
        </Text>
      </div>
    </div>
  );
}

function EvidenceTile({
  item,
  index,
  photos,
}: {
  item: UploadItem;
  index: number;
  photos: Evidence;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  if (item.status === 'failed') {
    return (
      <UploadTile
        state="failed"
        compact
        label={common(item.retryable ? 'photo.uploadFailed' : 'photo.rejected')}
        onRetry={item.retryable ? () => photos.uploads.retry(item.key) : undefined}
        retryLabel={common('action.retry')}
        onRemove={() => photos.uploads.remove(item.key)}
        removeLabel={common('photo.remove')}
        className={PHOTO_TILE}
      />
    );
  }
  if (item.status === 'uploading') {
    return (
      <UploadTile
        state="uploading"
        compact
        progress={item.progress}
        label={common('photo.uploading', { percent: Math.round(item.progress * 100) })}
        className={PHOTO_TILE}
      />
    );
  }
  const thumb = item.media?.variants.find((variant) => variant.name === 'thumb');
  return (
    <div className={`relative ${PHOTO_TILE}`}>
      <Photo
        file={item.preview}
        src={thumb?.url ?? item.media?.preview_url ?? undefined}
        placeholder={item.media?.placeholder}
        alt={t('dispute.photoNumber', { number: index + 1 })}
        className={PHOTO_TILE}
      />
      <IconButton
        icon="x"
        label={common('photo.remove')}
        onClick={() => photos.uploads.remove(item.key)}
        className="absolute -top-2 -right-2 size-7"
      />
    </div>
  );
}

function WithdrawSheet({
  busy,
  onClose,
  onConfirm,
}: {
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation('jobs');
  const { t: common } = useTranslation();
  useBackButton(onClose);
  return (
    <Sheet
      open
      title={t('dispute.withdrawTitle')}
      onClose={onClose}
      closeLabel={common('action.close')}
    >
      <div className="flex flex-col gap-3">
        <Text variant="sm">{t('dispute.withdrawText')}</Text>
        <Button variant="danger" full disabled={busy} aria-busy={busy} onClick={onConfirm}>
          {t('dispute.withdrawConfirm')}
        </Button>
        <Button variant="secondary" full disabled={busy} onClick={onClose}>
          {common('action.cancel')}
        </Button>
      </div>
    </Sheet>
  );
}

/** Сделка недоступна (`gone`) или не идёт и спора не было. */
function Closed({ gone, onDeal }: { gone: boolean; onDeal: () => void }) {
  const { t } = useTranslation('jobs');
  return (
    <section className="flex flex-col px-4 pt-10 pb-6">
      <EmptyState
        as="h1"
        size="h2"
        tone="neutral"
        icon="flag"
        title={gone ? t('deal.unavailable') : t('dispute.closed')}
        action={
          <Button variant="secondary" onClick={onDeal}>
            {t('dispute.toDeal')}
          </Button>
        }
      >
        <Text variant="sm">{gone ? t('deal.unavailableText') : t('dispute.closedText')}</Text>
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
    <section className="flex flex-col gap-3.5 px-4 pt-4 pb-6" aria-busy="true">
      {/* заголовок и строка сделки */}
      <div className="flex flex-col gap-1">
        <SkeletonText size="h2" screen className="w-3/5" />
        <SkeletonText size="cap" screen className="w-4/5" />
      </div>
      {/* «Что случилось?» — пять строк группы */}
      <div className="flex flex-col gap-2">
        <SkeletonText size="sm" screen className="w-1/3" />
        <RowsSkeleton rows={5} />
      </div>
      <FieldSkeleton tall />
      <div className="flex items-center gap-3">
        <Skeleton screen className={PHOTO_TILE} />
        <SkeletonText size="cap" screen className="w-3/5" />
      </div>
    </section>
  );
}
