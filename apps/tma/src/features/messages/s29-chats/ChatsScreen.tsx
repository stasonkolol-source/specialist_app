// S29 Сообщения (DEVELOPMENT_PLAN 6.4): вкладка таббара. Сегменты «Все / Я клиент / Я
// исполнитель»; строка диалога — инициалы и имя второй стороны, время последнего сообщения,
// контекст («Заявка: …» или «Из профиля специалиста», что со сделкой), последнее сообщение («Вы:
// …») и число непрочитанных. Внизу — памятка «телефоны и ссылки видны после договорённости».
// Нажатие — диалог S30. Гостю — пустой список: писать можно после входа.
import type { ConversationOut } from '@sosed/api-client';
import { getSession } from '@sosed/api-client';
import type { ChatRole } from '@sosed/hooks';
import { conversationItems, dealState, useConversations } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  FeedRow,
  Group,
  Heading,
  Segmented,
  Skeleton,
  Text,
  paletteFor,
} from '@sosed/ui-web';
import { useRouter } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { chatPath } from '../shared/paths.ts';
import { usePreview } from '../shared/preview.ts';

type Tab = 'all' | ChatRole;
const TABS: readonly Tab[] = ['all', 'client', 'performer'];

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
  const format = useFormat();
  const router = useRouter();
  const preview = usePreview();
  const name = conversation.counterpart_name ?? t('list.deleted');
  const at = new Date(conversation.last_message_at ?? conversation.created_at);
  const today = new Date().toDateString() === at.toDateString();
  const state = dealState(conversation);
  const context = conversation.job_title
    ? t('list.job', { title: conversation.job_title })
    : t('list.profile');
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
      meta={
        <>
          <time dateTime={at.toISOString()}>{today ? format.time(at) : format.date(at)}</time>
          {conversation.unread > 0 && (
            <Badge tone="ok" className="min-w-6 justify-center">
              <span aria-hidden="true">{conversation.unread}</span>
              <span className="sr-only">{t('list.unread', { count: conversation.unread })}</span>
            </Badge>
          )}
        </>
      }
    >
      <span className="flex flex-wrap items-center gap-x-2">
        <span>{context}</span>
        {state !== 'none' && <span className="font-semibold text-text">{t(`deal.${state}`)}</span>}
      </span>
      <span className="line-clamp-2 block text-text">{preview(conversation.last_message)}</span>
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
