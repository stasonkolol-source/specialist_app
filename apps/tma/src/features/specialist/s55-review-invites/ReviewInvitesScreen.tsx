// S55 «Отзывы до платформы» (DEVELOPMENT_PLAN 7.6а): специалист просит прошлых клиентов об
// отзыве. Правила (не больше пяти, отдельная вкладка вне рейтинга, проверка модератором),
// «4 из 5 · осталось 1» и приглашения со статусом: «Ждём отзыв», «На модерации», «Опубликован»,
// «Истекла», «Снят». MainButton «Создать ссылку» — шторка: «Кому» (заметка для себя, по желанию),
// затем готовая ссылка — «Скопировать» и MainButton «Отправить в Telegram» (выбор чата
// `t.me/share`). Ждущую отзыва ссылку можно скопировать снова или отозвать — подтверждение
// шторкой. Мест нет (`review_invites_full`) — объяснение вместо кнопки; профиль не опубликован
// (409 `review_invites_unavailable`) — объяснение, ссылку некому открыть. Вход — строка кабинета
// S33. Отклонение от артборда: MainButton — «Создать ссылку» (на артборде «Скопировать
// ссылку-приглашение»): ссылка одна на клиента, ей нужна заметка «Кому».
import type { ReviewInviteOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import {
  COPIED_TOAST_MS,
  INVITE_NAME_MAX,
  REVIEW_INVITES_LIMIT,
  useCreateReviewInvite,
  useMyProfile,
  useReviewInvites,
  useRevokeReviewInvite,
} from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, usePlatform } from '@sosed/platform';
import type { BadgeTone, IconName } from '@sosed/ui-web';
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  Field,
  Group,
  Heading,
  IconButton,
  Input,
  ProgressBar,
  RowIcon,
  Sheet,
  Text,
  Toast,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import { useEffect, useId, useRef, useState } from 'react';

import { LoadState } from '../shared/LoadState.tsx';
import { SaveError } from '../shared/SaveError.tsx';
import { useStepButton } from '../shared/flow.ts';
import { CABINET_PATHS } from '../shared/paths.ts';

type Status = 'waiting' | 'expired' | 'under_review' | 'published' | 'removed';
const STATUS_TONE: Record<Status, BadgeTone> = {
  waiting: 'mute',
  expired: 'mute',
  under_review: 'info',
  published: 'ok',
  removed: 'danger',
};
const STATUSES = Object.keys(STATUS_TONE) as Status[];
/** Статус строки; незнакомый (новый backend) — как истёкшая: без действий. */
const statusOf = (value: string): Status => STATUSES.find((known) => known === value) ?? 'expired';

/** Правила артборда: иконка и пара «жирное начало — пояснение». */
const RULES: { icon: IconName; title: 'limit' | 'tab' | 'moderation' }[] = [
  { icon: 'users', title: 'limit' },
  { icon: 'eye', title: 'tab' },
  { icon: 'shield', title: 'moderation' },
];

/** Открытая шторка: новая ссылка, готовая ссылка, подтверждение «Отозвать». */
type Dialog =
  | { kind: 'new' }
  | { kind: 'ready'; invite: ReviewInviteOut }
  | { kind: 'revoke'; invite: ReviewInviteOut }
  | null;

export function ReviewInvitesScreen() {
  const { t } = useTranslation('specialist');
  const router = useRouter();
  const profile = useMyProfile();
  const invites = useReviewInvites();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: CABINET_PATHS.home, replace: true });
  });
  const failed = [profile, invites].find((load) => load.isError);
  const ready = invites.data && profile.data !== undefined;

  return (
    <section className="flex flex-col gap-3.5 px-4 pt-3 pb-6">
      <div className="flex flex-col gap-1">
        <Heading variant="h2" as="h1">
          {t('invites.title')}
        </Heading>
        <Text variant="sm" secondary>
          {t('invites.lead')}
        </Text>
      </div>
      {ready ? (
        <Invites
          items={invites.data.items}
          taken={invites.data.taken}
          limit={invites.data.limit ?? REVIEW_INVITES_LIMIT}
          published={profile.data?.status === 'published'}
        />
      ) : (
        <LoadState
          shape="prices"
          error={failed ? failed.error : null}
          onRetry={() => {
            for (const load of [profile, invites]) if (load.isError) void load.refetch();
          }}
          retrying={profile.isRefetching || invites.isRefetching}
        />
      )}
    </section>
  );
}

function Invites({
  items,
  taken,
  limit,
  published: publishedProfile,
}: {
  items: ReviewInviteOut[];
  taken: number;
  limit: number;
  published: boolean;
}) {
  const { t } = useTranslation('specialist');
  const common = useTranslation().t;
  const platform = usePlatform();
  const create = useCreateReviewInvite();
  const revoke = useRevokeReviewInvite();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [name, setName] = useState('');
  // MainButton зовёт обработчик последнего рендера: нажатие сразу после ввода, до рендера, видело бы
  // прежнее имя — поэтому «Кому» читаем из ref, который обновляется в самом onChange
  const nameRef = useRef('');
  const [notice, setNotice] = useState<'copied' | 'failed' | null>(null);
  const listId = useId();
  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), COPIED_TOAST_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const code = create.error instanceof ApiError ? create.error.problem.code : null;
  // профиль сняли с публикации, пока экран был открыт, — сервер ответил 409
  const published = publishedProfile && code !== 'review_invites_unavailable';
  const full = taken >= limit || code === 'review_invites_full';
  const canCreate = published && !full;

  const close = () => {
    setDialog(null);
    create.reset();
    revoke.reset();
  };
  const copy = (url: string) =>
    void navigator.clipboard?.writeText(url).then(
      () => setNotice('copied'),
      () => setNotice('failed'),
    );
  const share = async (invite: ReviewInviteOut) => {
    const outcome = await platform.shareLink(invite.url, t('invites.shareText'));
    if (outcome !== 'shared') setNotice(outcome);
  };
  const submit = () => {
    if (create.isPending) return;
    create.mutate(
      { client_name: nameRef.current.trim() || null },
      {
        onSuccess: (invite) => {
          nameRef.current = '';
          setName('');
          setDialog({ kind: 'ready', invite });
        },
        // мест нет или профиль не опубликован — объяснение на экране, а не в шторке
        onError: (error) => {
          const conflict = error instanceof ApiError ? error.problem.code : null;
          if (conflict === 'review_invites_full' || conflict === 'review_invites_unavailable') {
            setDialog(null);
          }
        },
      },
    );
  };

  // MainButton — главное действие экрана или открытой шторки
  const button = useStepButton(
    dialog?.kind === 'new'
      ? { text: t('invites.create'), onClick: submit, loading: create.isPending }
      : dialog?.kind === 'ready'
        ? { text: t('invites.send'), onClick: () => void share(dialog.invite) }
        : {
            text: t('invites.create'),
            onClick: () => setDialog({ kind: 'new' }),
            visible: canCreate && dialog === null,
          },
  );

  return (
    <>
      <Card as="section" tight aria-label={t('invites.rules')}>
        {RULES.map(({ icon, title }) => (
          <div key={title} className="flex items-start gap-3">
            <RowIcon icon={icon} />
            <Text variant="sm" className="min-w-0 grow">
              <span className="font-semibold">{t(`invites.${title}Title`, { limit })}</span>{' '}
              {t(`invites.${title}Text`)}
            </Text>
          </div>
        ))}
      </Card>
      {!published && (
        <Banner tone="info" icon="lock">
          <span className="font-semibold">{t('invites.unavailableTitle')}.</span>{' '}
          {t('invites.unavailable')}
        </Banner>
      )}
      {published && full && <Banner tone="info">{t('invites.full', { limit })}</Banner>}
      <section aria-labelledby={listId} className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2 px-1">
          <Heading variant="h3" as="h2" id={listId}>
            {t('invites.list')}
          </Heading>
          <Text as="span" variant="cap" className="tabular-nums">
            {t('invites.taken', { taken, limit, left: Math.max(0, limit - taken) })}
          </Text>
        </div>
        <ProgressBar value={Math.min(taken, limit)} max={limit} label={t('invites.takenLabel')} />
        {items.length === 0 ? (
          <Card>
            <Text variant="sm" secondary>
              {t('invites.empty')}
            </Text>
          </Card>
        ) : (
          <Group>
            <ul className="m-0 list-none p-0">
              {items.map((invite) => (
                <InviteRow
                  key={invite.token}
                  invite={invite}
                  onCopy={() => copy(invite.url)}
                  onRevoke={() => setDialog({ kind: 'revoke', invite })}
                />
              ))}
            </ul>
          </Group>
        )}
        {revoke.isError && dialog === null && <SaveError error={revoke.error} />}
      </section>
      {create.isError && dialog === null && !full && published && (
        <SaveError error={create.error} />
      )}
      {dialog?.kind === 'new' && (
        <Sheet open title={t('invites.newTitle')} onClose={close} closeLabel={t('invites.close')}>
          <SheetBack onBack={close} />
          <Field label={t('invites.name')} hint={t('invites.nameHint')}>
            <Input
              value={name}
              maxLength={INVITE_NAME_MAX}
              placeholder={t('invites.namePlaceholder')}
              onChange={(event) => {
                nameRef.current = event.target.value;
                setName(event.target.value);
              }}
            />
          </Field>
          {create.isError && <SaveError error={create.error} />}
          {/* в браузере AppShell рисует MainButton поверх шторки — место под кнопку */}
          {!button.native && <div className="h-19" aria-hidden="true" />}
        </Sheet>
      )}
      {dialog?.kind === 'ready' && (
        <Sheet open title={t('invites.readyTitle')} onClose={close} closeLabel={t('invites.close')}>
          <SheetBack onBack={close} />
          <Text variant="sm" secondary>
            {t('invites.readyText')}
          </Text>
          <Input
            icon="link"
            readOnly
            value={dialog.invite.url.replace(/^https:\/\//, '')}
            aria-label={t('invites.link')}
            suffix={
              <IconButton
                plain
                icon="copy"
                label={t('invites.copy')}
                className="-mr-3"
                onClick={() => copy(dialog.invite.url)}
              />
            }
          />
          <Button variant="outline" full onClick={close}>
            {t('invites.done')}
          </Button>
          {!button.native && <div className="h-19" aria-hidden="true" />}
        </Sheet>
      )}
      {dialog?.kind === 'revoke' && (
        <Sheet
          open
          title={t('invites.revokeTitle')}
          onClose={close}
          closeLabel={t('invites.close')}
        >
          <SheetBack onBack={close} />
          <Text variant="sm" secondary>
            {t('invites.revokeText')}
          </Text>
          {revoke.isError && <SaveError error={revoke.error} />}
          <div className="flex flex-col gap-2">
            <Button
              variant="danger"
              full
              disabled={revoke.isPending}
              aria-busy={revoke.isPending}
              onClick={() => revoke.mutate(dialog.invite.token, { onSuccess: close })}
            >
              {t('invites.revoke')}
            </Button>
            <Button variant="outline" full onClick={close}>
              {t('invites.keep')}
            </Button>
          </div>
        </Sheet>
      )}
      {notice && (
        <Toast icon={notice === 'copied' ? 'link' : 'alert'}>
          {common(notice === 'copied' ? 'share.copied' : 'share.failed')}
        </Toast>
      )}
    </>
  );
}

/** «Назад» Telegram при открытой шторке закрывает её, а не экран. */
function SheetBack({ onBack }: { onBack: () => void }) {
  useBackButton(onBack);
  return null;
}

function InviteRow({
  invite,
  onCopy,
  onRevoke,
}: {
  invite: ReviewInviteOut;
  onCopy: () => void;
  onRevoke: () => void;
}) {
  const { t } = useTranslation('specialist');
  const format = useFormat();
  const status = statusOf(invite.status);
  const name = invite.reviewer_name ?? invite.client_name;
  const label = name ?? t('invites.unnamed');
  const when = (at: string | null) => format.relative(new Date(at ?? invite.created_at));
  const line = {
    waiting: () => t('invites.sent', { when: when(invite.created_at) }),
    expired: () => t('invites.expiredAt', { when: when(invite.expires_at) }),
    under_review: () => t('invites.received', { when: when(invite.used_at) }),
    published: () =>
      invite.rating === null
        ? when(invite.published_at)
        : t('invites.rated', { rating: invite.rating, when: when(invite.published_at) }),
    removed: () => t('invites.removedAt'),
  }[status]();
  return (
    <li className="flex items-start gap-3 border-b border-line py-3 pr-4 pl-4 last:border-b-0">
      {name ? <Avatar name={name} size="sm" /> : <RowIcon icon="link" neutral />}
      <div className="flex min-w-0 grow flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate font-semibold">{label}</span>
          <Badge tone={STATUS_TONE[status]}>{t(`invites.status.${status}`)}</Badge>
        </div>
        <div className="flex items-center justify-between gap-2">
          <Text as="span" variant="cap" className="min-w-0">
            {line}
          </Text>
          {status === 'waiting' && (
            <span className="-my-1 flex shrink-0 items-center gap-1">
              <IconButton
                plain
                icon="copy"
                label={t('invites.copyLabel', { name: label })}
                onClick={onCopy}
              />
              <Button
                size="sm"
                variant="outline"
                aria-label={t('invites.revokeLabel', { name: label })}
                onClick={onRevoke}
              >
                {t('invites.revoke')}
              </Button>
            </span>
          )}
        </div>
      </div>
    </li>
  );
}
