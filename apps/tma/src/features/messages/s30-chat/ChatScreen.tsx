// S30 Диалог (DEVELOPMENT_PLAN 6.4; ARCHITECTURE §11.5, §11.6): шапка — инициалы, имя второй
// стороны (у специалиста — ссылка на его карточку S08) и что со сделкой; справа «Договорились» —
// в прямом диалоге шторка условий (вторая сторона подтвердит, S53), клиенту в диалоге по отклику —
// «К откликам» (исполнителя выбирают на S23–S25). Сверху ленты — памятка «не вносите предоплату» и
// с чего начат диалог. Сообщения: свои справа, чужие слева; телефон или ссылка до договорённости —
// «•••» и подсказка «контакты откроются после договорённости»; просьба о предоплате — памятка;
// скрытое модерацией — словами (автор видит своё и что оно скрыто); отклик — карточкой с ценой;
// контакт — ссылкой; что со сделкой — системной строкой. Отправка сразу в ленте, неотправленное —
// «повторить». Лента опрашивается раз в 4 с (ETag), пока экран открыт; новое — прочитано.
// Закрытый диалог — без композера. «Пожаловаться» и «Заблокировать» — в шаге 4.7.
import type { ConversationOut, MessageOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import type { ChatEntry } from '@sosed/hooks';
import { MAX_MESSAGE, dealState, useChat } from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, useInsets } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Bubble,
  Button,
  ChatList,
  Composer,
  EmptyState,
  MaskedText,
  Skeleton,
  SystemNote,
  paletteFor,
} from '@sosed/ui-web';
import { useParams, useRouter } from '@tanstack/react-router';
import type { MouseEvent, ReactNode } from 'react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { MESSAGES_PATHS, managedJobPath, profilePath } from '../shared/paths.ts';
import { ProposeSheet } from './ProposeSheet.tsx';

const NOT_FOUND = 404;
/** Ближе к низу ленты, чем на столько пикселей, — новое прокручивается в вид само. */
const STICK_PX = 120;

export function ChatScreen() {
  const { conversationId } = useParams({ strict: false }) as { conversationId: string };
  const router = useRouter();
  useBackButton(() => {
    if (router.history.canGoBack()) router.history.back();
    else void router.navigate({ to: MESSAGES_PATHS.list, replace: true });
  });
  return <Chat key={conversationId} conversationId={conversationId} />;
}

function Chat({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation('messages');
  const chat = useChat(conversationId);
  const router = useRouter();

  if (chat.error) {
    if (chat.error instanceof ApiError && chat.error.status === NOT_FOUND) {
      return (
        <EmptyState
          as="h1"
          size="h2"
          tone="neutral"
          icon="chat"
          title={t('chat.unavailableTitle')}
          className="px-6 pt-10"
          action={
            <Button
              variant="secondary"
              onClick={() => void router.navigate({ to: MESSAGES_PATHS.list })}
            >
              {t('chat.toChats')}
            </Button>
          }
        >
          {t('chat.unavailableText')}
        </EmptyState>
      );
    }
    if (!chat.conversation) {
      return (
        <div className="pt-10">
          <LoadError error={chat.error} onRetry={() => router.invalidate()} retrying={false} />
        </div>
      );
    }
  }
  if (!chat.conversation) return <Loading />;
  return <Dialog conversation={chat.conversation} chat={chat} />;
}

type ChatState = ReturnType<typeof useChat>;

function Dialog({ conversation, chat }: { conversation: ConversationOut; chat: ChatState }) {
  const { t } = useTranslation('messages');
  const format = useFormat();
  const insets = useInsets();
  const [draft, setDraft] = useState('');
  const [proposing, setProposing] = useState(false);
  const [proposed, setProposed] = useState(false);
  const writable = conversation.status === 'open';
  const name = conversation.counterpart_name ?? t('list.deleted');

  const bottom = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const onScroll = () => {
      const left = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
      stick.current = left < STICK_PX;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const count = chat.entries.length;
  useLayoutEffect(() => {
    if (count > 0 && stick.current) bottom.current?.scrollIntoView?.({ block: 'end' });
  }, [count]);

  const send = () => {
    stick.current = true;
    chat.send(draft);
    setDraft('');
  };

  const started = new Date(conversation.created_at);
  return (
    <div className="flex min-h-[calc(100dvh-var(--tg-top,0px))] flex-col">
      <Header conversation={conversation} name={name} onPropose={() => setProposing(true)} />
      <div className="flex flex-1 flex-col justify-end">
        <ChatList label={t('list.title')} className="pb-4">
          <Banner tone="warn" icon="alert">
            {t('chat.safety')}
          </Banner>
          {chat.hasEarlier && (
            <Button
              variant="secondary"
              size="sm"
              className="self-center"
              onClick={chat.loadEarlier}
              disabled={chat.loadingEarlier}
              aria-busy={chat.loadingEarlier}
            >
              {t('chat.earlier')}
            </Button>
          )}
          <SystemNote>
            {conversation.job_title
              ? t('chat.startedJob', {
                  title: conversation.job_title,
                  date: format.date(started),
                })
              : t('chat.startedProfile', { date: format.date(started) })}
          </SystemNote>
          {chat.entries.map((entry) => (
            <Entry
              key={entryKey(entry)}
              entry={entry}
              conversation={conversation}
              onRetry={chat.retry}
            />
          ))}
          {proposed && <SystemNote icon="check">{t('chat.propose.sent')}</SystemNote>}
          <div ref={bottom} />
        </ChatList>
      </div>
      <SendError error={chat.sendError} />
      {writable ? (
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={send}
          placeholder={t('chat.placeholder')}
          label={t('chat.placeholder')}
          sendLabel={t('chat.send')}
          maxLength={MAX_MESSAGE}
          bottomInset={insets.bottom}
        />
      ) : (
        <div
          className="sticky bottom-0 bg-bg px-4 pt-3"
          style={{ paddingBottom: insets.bottom + 12 }}
        >
          <Banner tone="info" role="status">
            {t('chat.closed')}
          </Banner>
        </div>
      )}
      <ProposeSheet
        open={proposing}
        conversationId={conversation.id}
        onClose={() => setProposing(false)}
        onProposed={() => {
          setProposing(false);
          setProposed(true);
        }}
      />
    </div>
  );
}

function Header({
  conversation,
  name,
  onPropose,
}: {
  conversation: ConversationOut;
  name: string;
  onPropose: () => void;
}) {
  const { t } = useTranslation('messages');
  const router = useRouter();
  const state = dealState(conversation);
  const settled = state === 'proposed' || state === 'agreed' || state === 'disputed';
  const open = conversation.status === 'open';
  const profileId = conversation.counterpart_profile_id;
  const person = (
    <>
      <Avatar name={name} size="sm" palette={paletteFor(conversation.counterpart_id)} />
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-semibold">{name}</span>
        <span className="text-cap text-text2">{t(`deal.${state}`)}</span>
      </span>
    </>
  );
  const toProfile = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (profileId) void router.navigate({ to: profilePath(profileId) });
  };

  let action: ReactNode = null;
  if (open && !settled && conversation.kind === 'direct') {
    action = (
      <Button size="sm" onClick={onPropose}>
        {t('chat.agree')}
      </Button>
    );
  } else if (
    open &&
    !settled &&
    conversation.kind === 'job_response' &&
    conversation.my_role === 'client' &&
    conversation.job_id
  ) {
    const jobId = conversation.job_id;
    action = (
      <Button
        size="sm"
        variant="secondary"
        onClick={() => void router.navigate({ to: managedJobPath(jobId) })}
      >
        {t('chat.openResponses')}
      </Button>
    );
  }

  return (
    <header
      aria-label={name}
      className="sticky top-0 z-10 flex items-center gap-2.5 border-0 border-b border-solid border-line bg-bg px-4 py-2.5"
    >
      {profileId ? (
        <a
          href={router.history.createHref(profilePath(profileId))}
          onClick={toProfile}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-text"
        >
          {person}
        </a>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2.5">{person}</div>
      )}
      {action}
    </header>
  );
}

function Entry({
  entry,
  conversation,
  onRetry,
}: {
  entry: ChatEntry;
  conversation: ConversationOut;
  onRetry: (clientMsgId: string) => void;
}) {
  const { t } = useTranslation('messages');
  const format = useFormat();
  if (entry.type === 'pending') {
    const { pending } = entry;
    return (
      <Bubble
        side="out"
        failed={pending.failed}
        onRetry={() => onRetry(pending.clientMsgId)}
        status={pending.failed ? t('chat.failed') : t('chat.sending')}
      >
        {pending.body}
      </Bubble>
    );
  }
  const { message } = entry;
  const time = format.time(new Date(message.created_at));
  if (message.kind === 'system')
    return <SystemEvent message={message} conversation={conversation} />;
  const side = message.mine ? 'out' : 'in';
  return (
    <>
      <Bubble
        side={side}
        time={time}
        status={message.mine && message.hidden ? t('chat.hiddenOwn') : undefined}
      >
        <MessageBody message={message} />
      </Bubble>
      {message.masked && <SystemNote icon="lock">{t('chat.masked')}</SystemNote>}
      {message.prepayment && !message.mine && (
        <SystemNote icon="alert">{t('chat.prepayment')}</SystemNote>
      )}
    </>
  );
}

function MessageBody({ message }: { message: MessageOut }) {
  const { t } = useTranslation('messages');
  const format = useFormat();
  if (message.hidden && !message.mine) return <em>{t('chat.hidden')}</em>;
  if (message.kind === 'contact_share' && message.contact) {
    const { type, value } = message.contact;
    const href = type === 'telegram' ? `https://t.me/${value.replace(/^@/, '')}` : `tel:${value}`;
    return (
      <a href={href} className="font-semibold text-inherit underline">
        {t(`chat.contact.${type}`, { value })}
      </a>
    );
  }
  if (message.body === null) return <em>{t('chat.erased')}</em>;
  if (message.kind === 'offer') {
    const offer = message.offer;
    const amount = offer?.price_amount;
    const priceType = offer?.price_type;
    const price = offerPrice(format, priceType, amount);
    const when = typeof offer?.availability_note === 'string' ? offer.availability_note : null;
    return (
      <span className="flex flex-col gap-1">
        <span className="text-cap font-semibold opacity-80">{t('chat.offer')}</span>
        <MaskedText text={message.body} />
        {price && <span className="font-semibold">{t('chat.offerPrice', { price })}</span>}
        {when && <span>{t('chat.offerWhen', { when })}</span>}
      </span>
    );
  }
  return <MaskedText text={message.body} />;
}

function SystemEvent({
  message,
  conversation,
}: {
  message: MessageOut;
  conversation: ConversationOut;
}) {
  const { t } = useTranslation('messages');
  const event = message.event;
  if (!event) return null;
  if (event.type === 'deal_agreed')
    return <SystemNote icon="check-circle">{t('chat.event.dealAgreed')}</SystemNote>;
  if (event.type === 'deal_cancelled')
    return <SystemNote icon="x">{t('chat.event.dealCancelled')}</SystemNote>;
  const mine = event.by === conversation.my_role;
  return (
    <SystemNote icon="check">
      {mine ? t('chat.event.dealProposedMine') : t('chat.event.dealProposedTheirs')}
    </SystemNote>
  );
}

function SendError({ error }: { error: unknown }) {
  const { t } = useTranslation('messages');
  const { t: common } = useTranslation();
  if (!error) return null;
  const code = error instanceof ApiError ? error.problem.code : null;
  const text =
    code === 'messages_limit'
      ? t('chat.limit')
      : code === 'conversation_closed'
        ? t('chat.closed')
        : common('error.text');
  return (
    <div className="px-4 pb-2">
      <Banner tone="danger" role="alert">
        {text}
      </Banner>
    </div>
  );
}

/** Цена отклика словами: «3 500 RSD», «от …», «… в час», «договорная». */
function offerPrice(
  format: ReturnType<typeof useFormat>,
  type: unknown,
  amount: unknown,
): string | null {
  if (type === 'negotiable') return format.price({ type: 'negotiable' });
  if ((type === 'fixed' || type === 'from' || type === 'hourly') && typeof amount === 'number') {
    return format.price({ type, min: amount });
  }
  return null;
}

function entryKey(entry: ChatEntry): string {
  return entry.type === 'message' ? entry.message.id : `pending:${entry.pending.clientMsgId}`;
}

function Loading() {
  return (
    <div className="flex flex-col gap-3 px-4 pt-4">
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-16 w-2/3" />
      <Skeleton className="ml-auto h-12 w-1/2" />
      <Skeleton className="h-16 w-3/4" />
    </div>
  );
}
