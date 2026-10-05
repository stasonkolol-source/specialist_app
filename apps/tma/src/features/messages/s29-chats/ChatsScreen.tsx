// S29 Сообщения (DEVELOPMENT_PLAN 6.4): вкладка таббара. Сегменты «Все / Я клиент / Я
// исполнитель»; строка диалога — инициалы и имя второй стороны, время последнего сообщения
// коротко, как в Telegram («16:05», «вчера», «пт», «2 окт»: длинная дата отнимала место у имени),
// контекст («Заявка: …» или «Из профиля специалиста») с плашкой «что со сделкой» или «Отклик»,
// последнее сообщение («Вы: …», скрытый сервером контакт — плашкой «контакт скрыт», как в
// диалоге) и под временем — число непрочитанных, как на артборде. Внизу — памятка «телефоны и
// ссылки видны после договорённости». Нажатие — диалог S30. Гостю — пустой список: писать можно
// после входа.
import type { ConversationOut } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import type { ChatRole, DealState } from '@sosed/hooks';
import { conversationItems, dealState, useConversations } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import type { BadgeTone } from '@sosed/ui-web';
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  FeedRow,
  Group,
  Heading,
  MaskedText,
  Segmented,
  Skeleton,
  Text,
  paletteFor,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { useListTime } from '../shared/dates.ts';
import { chatPath } from '../shared/paths.ts';
import { usePreview } from '../shared/preview.ts';

type Tab = 'all' | ChatRole;
const TABS: readonly Tab[] = ['all', 'client', 'performer'];
/** Плашка сделки в строке диалога — тоном, как статус на S26. */
const DEAL_TONE: Record<Exclude<DealState, 'none'>, BadgeTone> = {
  proposed: 'info',
  agreed: 'ok',
  completed: 'ok',
  cancelled: 'mute',
  disputed: 'urgent',
};

export function ChatsScreen() {
  const { t } = useTranslation('messages');
  const [tab, setTab] = useState<Tab>('all');
  const signedIn = getSession() !== null;
  return (
    <section className="flex flex-col gap-3 px-4 pt-3 pb-6">
      <Heading variant="h1">{t('list.title')}</Heading>
      <Segmented
        label={t('list.title')}
        value={tab}
        onChange={setTab}
        options={TABS.map((value) => ({ value, label: t(`list.tabs.${value}`) }))}
      />
      {signedIn ? <Conversations role={tab === 'all' ? null : tab} /> : <Empty all />}
    </section>
  );
}

function Conversations({ role }: { role: ChatRole | null }) {
  const { t } = useTranslation('messages');
  const list = useConversations(role);
  if (list.isError) {
    return (
      <LoadError
        error={list.error}
        onRetry={() => void list.refetch()}
        retrying={list.isRefetching}
      />
    );
  }
  if (!list.data) {
    return (
      <Group>
        {[0, 1, 2].map((key) => (
          <div key={key} className="flex gap-3 px-4 py-3">
            <Skeleton radius="round" className="size-10" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          </div>
        ))}
      </Group>
    );
  }
  const items = conversationItems(list.data);
  if (items.length === 0) return <Empty all={role === null} />;
  return (
    <>
      <Group>
        {items.map((conversation) => (
          <ConversationRow key={conversation.id} conversation={conversation} />
        ))}
      </Group>
      {list.hasNextPage && (
        <Button
          variant="secondary"
          full
          onClick={() => void list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
          aria-busy={list.isFetchingNextPage}
        >
          {t('list.more')}
        </Button>
      )}
      <Text variant="cap" secondary className="text-center">
        {t('list.hint')}
      </Text>
    </>
  );
}

function ConversationRow({ conversation }: { conversation: ConversationOut }) {
  const { t } = useTranslation('messages');
  const listTime = useListTime();
  const router = useRouter();
  const preview = usePreview();
  const name = conversation.counterpart_name ?? t('list.deleted');
  const at = new Date(conversation.last_message_at ?? conversation.created_at);
  const state = dealState(conversation);
  const context = conversation.job_title
    ? t('list.job', { title: conversation.job_title })
    : t('list.profile');
  // плашка: что со сделкой, а в диалоге по отклику без сделки — «Отклик» (сообщение отклика тогда
  // без приписки «Отклик:»)
  const badge =
    state !== 'none' ? (
      <Badge tone={DEAL_TONE[state]}>{t(`deal.${state}`)}</Badge>
    ) : conversation.kind === 'job_response' ? (
      <Badge tone="info">{t('list.response')}</Badge>
    ) : null;
  const path = chatPath(conversation.id);
  const open = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    void router.navigate({ to: path });
  };
  return (
    <FeedRow
      href={router.history.createHref(path)}
      onClick={open}
      leading={<Avatar name={name} size="md" palette={paletteFor(conversation.counterpart_id)} />}
      title={name}
      meta={<time dateTime={at.toISOString()}>{listTime(at)}</time>}
    >
      {/* длинная заявка переносится сама, плашка остаётся справа от неё, как на артборде */}
      <span className="flex items-center gap-1.5">
        <span className="min-w-0 text-cap">{context}</span>
        {badge}
      </span>
      {/* непрочитанные — под временем, в строке последнего сообщения, как на артборде */}
      <span className="mt-0.5 flex items-center justify-between gap-3">
        {/* длинное слово или ссылка переносится и обрезается «…» на второй строке, а не уходит за
            край карточки (UXM-18) */}
        <span className="line-clamp-2 min-w-0 text-text wrap-anywhere">
          <MaskedText
            text={preview(conversation.last_message)}
            label={t('mask.text')}
            hiddenLabel={t('mask.label')}
          />
        </span>
        {conversation.unread > 0 && (
          <span className="inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full bg-accent px-1.5 text-badge text-accent-ink">
            <span aria-hidden="true">{conversation.unread}</span>
            <span className="sr-only">{t('list.unread', { count: conversation.unread })}</span>
          </span>
        )}
      </span>
    </FeedRow>
  );
}

function Empty({ all }: { all: boolean }) {
  const { t } = useTranslation('messages');
  return all ? (
    <EmptyState as="h2" icon="chat" title={t('list.empty.title')}>
      {t('list.empty.text')}
    </EmptyState>
  ) : (
    <EmptyState as="h2" icon="chat" title={t('list.emptyRole')} />
  );
}
