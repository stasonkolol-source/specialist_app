// S30 Диалог (DEVELOPMENT_PLAN 6.4; ARCHITECTURE §11.5, §11.6): шапка — инициалы, имя второй
// стороны (у специалиста — ссылка на его карточку S08), что со сделкой (только когда сделка есть,
// без «Сделки пока нет») и справа одно главное действие, коротко: шапка не прокручивается, а
// диалог открывается в конце переписки. Без сделки — «Договориться» (шторка условий, вторая
// сторона подтвердит, S53; вторичной, пока собеседник не ответил: сначала договариваются
// словами, UX_GUIDANCE №8); клиенту в диалоге по отклику,
// пока исполнитель не выбран, — «К откликам» (выбирают на S23–S25); сделка предложена, идёт или
// под спором — «Сделка» (S26, как на артборде S54); сделка позади — в прямом диалоге снова
// «Договориться» (та же шторка, «что делаем» — из прошлой сделки), клиенту по отклику после
// завершённой — «Заказать снова» (прямой диалог с этим специалистом, как «Написать» на S08). Под
// шапкой — полоса сделки диалога (позади — «Прошлая сделка») или, если сделки нет, а контакты
// пары открыты, — «Вы уже договаривались»; второй строкой в ней — Telegram второй стороны и
// «Поделиться контактом» (шторка S54, 6.5; из сделки S26 — сразу открытой, `?share`). Открыты ли
// контакты, решает сервер (`contacts_open`): эта пара уже договаривалась — в этом диалоге или в
// другом — значит, открыты (ADR-0010, решение владельца 2026-10-04). Имя и что со сделкой не
// обрезаются и при 360 px, а попап «⋯» Telegram — не больше трёх кнопок. В начале диалога — памятка
// «не вносите предоплату» (один раз, с началом ленты, а не над каждой подгрузкой) и с чего начат
// диалог; в пустом диалоге клиента — что написать и как придёт ответ (№8). Над первым сообщением
// каждого дня — подпись дня
// («Сегодня», «Вчера», «2 октября»). Сообщения: свои справа, чужие слева; телефон или ссылка до
// договорённости — плашка «контакт скрыт» и подсказка «контакты откроются после договорённости»;
// просьба о предоплате — памятка; скрытое модерацией — словами (автор видит своё и что оно
// скрыто); отклик — карточкой с ценой; контакт — ссылкой; что со сделкой — системной строкой: после
// «Предложить» — одна строка со сроком ответа, отклонённое предложение — «Предложение не принято»
// (№14).
// Отправка сразу в ленте, неотправленное — «повторить». Лента опрашивается раз в 4 с (ETag), пока
// экран открыт; новое — прочитано. Закрытый диалог — без композера. «⋯» в шапке (4.7) — попап
// Telegram: «Пожаловаться» (шторка S46 на собеседника с этим диалогом) и «Заблокировать» с
// подтверждением или «Разблокировать». Блокировка в любую сторону — переписка только для чтения:
// вместо композера «Вы заблокировали собеседника» с «Разблокировать» или «Собеседник недоступен».
import type { ConversationOut, MessageOut } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import type { ChatEntry } from '@sosed/hooks';
import {
  MAX_MESSAGE,
  blockedIds,
  blockedUserOf,
  cachedConversation,
  dealState,
  openReport,
  useBlocks,
  useChat,
  useStartConversation,
  useToggleBlock,
} from '@sosed/hooks';
import { useFormat, useTranslation } from '@sosed/i18n';
import { useBackButton, useInsets, usePlatform } from '@sosed/platform';
import {
  Avatar,
  Banner,
  Bubble,
  Button,
  ChatList,
  ChatSkeleton,
  Composer,
  DayLabel,
  EmptyState,
  IconButton,
  MaskedText,
  Skeleton,
  SkeletonText,
  SystemNote,
  paletteFor,
} from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter, useSearch } from '@tanstack/react-router';
import type { MouseEvent } from 'react';
import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { LoadError } from '../shared/LoadError.tsx';
import { dayKey, useDayLabel } from '../shared/dates.ts';
import {
  MESSAGES_PATHS,
  chatPath,
  dealPath,
  managedJobPath,
  profilePath,
} from '../shared/paths.ts';
import { ProposeSheet } from './ProposeSheet.tsx';
import { ShareContactSheet } from './ShareContactSheet.tsx';

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
  const queryClient = useQueryClient();

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
  if (!chat.conversation) {
    return <Loading conversation={cachedConversation(queryClient, conversationId)} />;
  }
  return <Dialog conversation={chat.conversation} chat={chat} />;
}

type ChatState = ReturnType<typeof useChat>;

function Dialog({ conversation, chat }: { conversation: ConversationOut; chat: ChatState }) {
  const { t } = useTranslation('messages');
  const { t: common } = useTranslation();
  const dayLabel = useDayLabel();
  const insets = useInsets();
  const router = useRouter();
  const [proposing, setProposing] = useState(false);
  const { share: shareAsked } = useSearch({ strict: false }) as { share?: true };
  const contactsOpen = conversation.contacts_open;
  const [sharing, setSharing] = useState(Boolean(shareAsked) && contactsOpen);
  const block = useBlockState(conversation);
  const writable = conversation.status === 'open' && block.state === null;
  const name = conversation.counterpart_name ?? t('list.deleted');
  const again = writable ? againOf(conversation) : null;
  const reorder = useStartConversation();
  const orderAgain = () => {
    const profileId = conversation.counterpart_profile_id;
    if (!profileId) return;
    reorder.mutate(
      { profile_id: profileId },
      { onSuccess: (started) => void router.navigate({ to: chatPath(started.id) }) },
    );
  };
  // собеседник уже ответил: до этого «Договориться» — вторичной, сначала договариваются словами
  const replied = chat.entries.some(
    (entry) => entry.type === 'message' && !entry.message.mine && entry.message.kind !== 'system',
  );
  const actions = useActions(conversation, writable, again, replied, {
    propose: () => setProposing(true),
    order: orderAgain,
    ordering: reorder.isPending,
    share: () => setSharing(true),
  });

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
    // к концу документа, а не к последнему сообщению: иначе его закрывает прилипший композер
    if (count > 0 && stick.current) window.scrollTo(0, document.documentElement.scrollHeight);
  }, [count]);

  const send = (text: string) => {
    stick.current = true;
    chat.send(text);
  };

  // дата начала диалога — подписью дня над строкой «Диалог из профиля…», дальше — над первым
  // сообщением каждого следующего дня
  const started = new Date(conversation.created_at);
  const now = new Date();
  return (
    <div className="flex min-h-[calc(100dvh-var(--tg-top,0px))] flex-col">
      <Header
        conversation={conversation}
        name={name}
        action={actions.header}
        onMenu={() => void block.menu(name)}
      />
      {actions.bar && (
        <DealBar
          conversation={conversation}
          withDeal={actions.withDeal}
          link={actions.dealLink}
          actions={actions.inBar}
        />
      )}
      <div className="flex flex-1 flex-col justify-end">
        <ChatList label={t('list.title')} className="pb-4">
          {/* памятка — в начале диалога, а не над каждой подгрузкой ленты (§5) */}
          {!chat.hasEarlier && (
            <Banner tone="warn" icon="alert">
              {t('chat.safety')}
            </Banner>
          )}
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
          <DayLabel dateTime={dayKey(started)}>{dayLabel(started, now)}</DayLabel>
          <SystemNote>
            {conversation.job_title
              ? t('chat.startedJob', { title: conversation.job_title })
              : t('chat.startedProfile')}
          </SystemNote>
          {/* пустой диалог клиента: что написать и как он узнает об ответе (№8) */}
          {writable && conversation.my_role === 'client' && chat.entries.length === 0 && (
            <SystemNote>{t('chat.emptyHint', { name })}</SystemNote>
          )}
          {withDays(chat.entries, dayKey(started)).map((row) =>
            row.type === 'day' ? (
              <DayLabel key={row.key} dateTime={dayKey(row.date)}>
                {dayLabel(row.date, now)}
              </DayLabel>
            ) : (
              <Entry
                key={row.key}
                entry={row.entry}
                conversation={conversation}
                onRetry={chat.retry}
              />
            ),
          )}
        </ChatList>
      </div>
      <SendError error={chat.sendError} />
      {block.failed && (
        <div className="px-4 pt-2">
          <Banner tone="danger" role="alert">
            {t('chat.blockFailed')}
          </Banner>
        </div>
      )}
      {reorder.isError && (
        <div className="px-4 pt-2">
          <Banner tone="danger" role="alert">
            {t('chat.orderAgainFailed')}
          </Banner>
        </div>
      )}
      {writable ? (
        <DraftComposer onSend={send} bottomInset={insets.bottom} />
      ) : (
        <div
          className="sticky bottom-0 flex flex-col gap-2 bg-bg px-4 pt-3"
          style={{ paddingBottom: insets.bottom + 12 }}
        >
          <Banner tone="info" icon={block.state ? 'ban' : undefined} role="status">
            {block.state === 'mine'
              ? t('chat.blockedByMe')
              : block.state === 'theirs'
                ? t('chat.blockedByThem')
                : t('chat.closed')}
          </Banner>
          {block.state === 'mine' && (
            <Button variant="secondary" full disabled={block.busy} onClick={block.unblock}>
              {common('action.unblock')}
            </Button>
          )}
        </div>
      )}
      <ShareContactSheet
        open={sharing}
        conversationId={conversation.id}
        onClose={() => setSharing(false)}
      />
      <ProposeSheet
        open={proposing}
        conversationId={conversation.id}
        initialTitle={again === 'propose' ? conversation.deal?.title : undefined}
        onClose={() => setProposing(false)}
        // строка «Условия отправлены…» — от сервера: шторка закрывается, когда лента её уже знает
        onProposed={() => setProposing(false)}
      />
    </div>
  );
}

/** Блокировка со второй стороной (4.7): моя — по списку блокировок (он меняется сразу, до
 *  ответа сервера), чужая — по диалогу. `menu` — попап «⋯» шапки: жалоба или (раз)блокировка. */
function useBlockState(conversation: ConversationOut) {
  const { t } = useTranslation('messages');
  const { t: common } = useTranslation();
  const platform = usePlatform();
  const blocks = useBlocks();
  const toggle = useToggleBlock();
  const other = conversation.counterpart_id;
  const mine = blocks.data ? blockedIds(blocks.data).has(other) : conversation.blocked_by_me;
  const theirs = conversation.blocked && !conversation.blocked_by_me;
  const state: 'mine' | 'theirs' | null = mine ? 'mine' : theirs ? 'theirs' : null;
  const user = (name: string) =>
    blockedUserOf({
      user_id: other,
      display_name: name,
      profile_id: conversation.counterpart_profile_id,
    });

  const menu = async (name: string) => {
    const choice = await platform.popup({
      message: name,
      buttons: [
        { id: 'report', text: common('action.report') },
        mine
          ? { id: 'unblock', text: common('action.unblock') }
          : { id: 'block', type: 'destructive', text: common('action.block') },
        { id: 'cancel', type: 'cancel' },
      ],
    });
    if (choice === 'report') {
      openReport({
        type: 'user',
        id: other,
        userId: other,
        name,
        profileId: conversation.counterpart_profile_id ?? undefined,
        conversationId: conversation.id,
      });
    } else if (choice === 'unblock') {
      toggle.mutate({ user: user(name), on: false });
    } else if (choice === 'block' && (await platform.confirm(t('chat.blockConfirm')))) {
      toggle.mutate({ user: user(name), on: true });
    }
  };
  const unblock = () =>
    toggle.mutate({ user: user(conversation.counterpart_name ?? ''), on: false });
  return { state, menu, unblock, busy: toggle.isPending, failed: toggle.isError };
}

/** Что можно снова, когда сделка позади: в прямом диалоге — новые условия той же шторкой (сервер
 *  разрешает после завершения или отмены), клиенту в диалоге по отклику после завершённой — прямой
 *  диалог с этим специалистом (здесь сервер ответит `cannot_propose`). После отмены по отклику —
 *  по-прежнему «К откликам»: заявка снова открыта. Исполнителю по отклику — ничего нового. */
type Again = 'propose' | 'order' | null;

function againOf(conversation: ConversationOut): Again {
  const state = dealState(conversation);
  if (state !== 'completed' && state !== 'cancelled') return null;
  if (conversation.kind === 'direct') return 'propose';
  const client = conversation.my_role === 'client';
  return client && state === 'completed' && conversation.counterpart_profile_id ? 'order' : null;
}

/** Действие диалога: главное — кнопкой в шапке, остальные — текстом второй строкой полосы. */
interface Action {
  key: string;
  label: string;
  onClick: () => void;
  /** Подпись для диктора, когда на кнопке не всё: «Telegram: @aleksey_m». */
  title?: string;
  /** Ждём ответа сервера: «Заказать снова» открывает диалог. */
  busy?: boolean;
  /** Вторичной: «К откликам» и «Сделка» уводят на другой экран, а не договариваются. */
  secondary?: boolean;
}

/** Что можно сделать в диалоге и где. Главное — всегда кнопкой в шапке: она не прокручивается, а
 *  диалог открывается в конце переписки, и полоса под шапкой уходит вверх («заказать снова» было
 *  не найти). Подпись — короткая, чтобы имя и что со сделкой помещались и при 360 px:
 *  «Договориться» — без сделки, а после завершённой или отменённой в прямом диалоге — снова (что
 *  сделка позади, говорит строка под именем); «К откликам» — клиенту по отклику, пока исполнитель
 *  не выбран; «Заказать снова» — ему же после завершённой; «Сделка» (S26, как в шапке артборда
 *  S54) — пока сделка предложена, идёт или под спором, и когда снова отсюда нельзя. Полоса под
 *  шапкой — сделка диалога (`withDeal`) или открытые контакты без сделки (пара договаривалась в
 *  другом диалоге); второй строкой в ней — Telegram и «Поделиться контактом», без повтора шапки. */
function useActions(
  conversation: ConversationOut,
  writable: boolean,
  again: Again,
  replied: boolean,
  on: { propose: () => void; order: () => void; ordering: boolean; share: () => void },
) {
  const { t } = useTranslation('messages');
  const router = useRouter();
  const platform = usePlatform();
  const state = dealState(conversation);
  const withDeal = dealInBar(conversation, writable);
  const telegram = conversation.counterpart_telegram;
  const deal = conversation.deal;

  let main: Action | null = null;
  if (again === 'propose' || (writable && conversation.kind === 'direct' && state === 'none')) {
    // в пустом диалоге акцентная «Договориться» спорит с первым сообщением (№8)
    main = { key: 'agree', label: t('chat.agree'), onClick: on.propose, secondary: !replied };
  } else if (again === 'order') {
    main = { key: 'order', label: t('chat.orderAgain'), onClick: on.order, busy: on.ordering };
  } else if (
    writable &&
    conversation.kind === 'job_response' &&
    conversation.my_role === 'client' &&
    conversation.job_id &&
    (state === 'none' || state === 'cancelled')
  ) {
    // исполнителя выбирают на S23–S25: условия здесь сервер не примет; после отмены заявка
    // снова открыта
    const path = managedJobPath(conversation.job_id);
    main = {
      key: 'responses',
      label: t('chat.openResponses'),
      onClick: () => void router.navigate({ to: path }),
      secondary: true,
    };
  } else if (withDeal && deal) {
    // второй стороне ждущего предложения там — S53 (6.5)
    const path = dealPath(deal.id);
    main = {
      key: 'deal',
      label: t('chat.deal'),
      onClick: () => void router.navigate({ to: path }),
      secondary: true,
    };
  }
  const more: Action[] = [];
  if (telegram) {
    more.push({
      key: 'telegram',
      label: t('chat.telegram'),
      title: `${t('chat.telegram')}: ${telegram}`,
      onClick: () => platform.openTelegramLink(telegramLink(telegram)),
    });
  }
  // делятся по сделке диалога, пока контакты открыты; под спором — нет. Сделка есть — есть и полоса
  if (writable && conversation.contacts_open && state !== 'none' && state !== 'disputed') {
    more.push({ key: 'share', label: t('chat.shareContact'), onClick: on.share });
  }
  return {
    header: main,
    bar: withDeal || Boolean(telegram),
    withDeal,
    // «Сделка» в шапке — ссылка на неё в полосе не повторяется
    dealLink: main?.key !== 'deal',
    inBar: more,
  };
}

/** Сделка диалога в полосе: предложена, идёт, под спором или позади. Отменённая — только если до
 *  отмены договорились (контакты открыты): отклонённое предложение полосы не оставляет. */
function dealInBar(conversation: ConversationOut, writable: boolean): boolean {
  const state = dealState(conversation);
  if (!conversation.deal || state === 'none') return false;
  return state !== 'cancelled' || (writable && conversation.contacts_open);
}

/** Полоса под шапкой: сделка диалога (завершённая и отменённая — «Прошлая сделка»), ссылкой на
 *  S26, если в шапке не «Сделка», или, без сделки, «вы уже договаривались — контакты открыты».
 *  Второй строкой — Telegram и «Поделиться контактом» (`useActions`). */
function DealBar({
  conversation,
  withDeal,
  link,
  actions,
}: {
  conversation: ConversationOut;
  withDeal: boolean;
  link: boolean;
  actions: readonly Action[];
}) {
  const { t } = useTranslation('messages');
  const router = useRouter();
  const state = dealState(conversation);
  const deal = withDeal ? conversation.deal : null;
  // по краю ленты и аватара в шапке — 12 px
  return (
    <div className="px-3 pt-3">
      <Banner
        tone={deal && state === 'proposed' ? 'warn' : 'info'}
        icon={deal ? 'briefcase' : 'check-circle'}
      >
        {deal ? (
          <>
            {t(
              state === 'completed' || state === 'cancelled' ? 'chat.dealBarPast' : 'chat.dealBar',
              { title: deal.title },
            )}
            {link && (
              <>
                {' '}
                <a
                  href={router.history.createHref(dealPath(deal.id))}
                  onClick={(event: MouseEvent<HTMLAnchorElement>) => {
                    event.preventDefault();
                    void router.navigate({ to: dealPath(deal.id) });
                  }}
                >
                  {t('chat.dealOpen')}
                </a>
              </>
            )}
          </>
        ) : (
          t('chat.contactsOpen')
        )}
        {actions.length > 0 && (
          // кнопки по 44 px в высоту: строка заходит в нижний отступ полосы, текст — на месте
          <span className="-mb-3 flex flex-wrap gap-x-4">
            {actions.map((action) => (
              <BarButton key={action.key} action={action} />
            ))}
          </span>
        )}
      </Banner>
    </div>
  );
}

/** Действие в полосе — текстом, как её ссылки: шторку или Telegram открывает кнопка, а не
 *  переход. */
function BarButton({ action }: { action: Action }) {
  return (
    <button
      type="button"
      aria-label={action.title}
      className="inline-flex min-h-11 cursor-pointer items-center border-0 bg-transparent p-0 font-semibold text-inherit underline"
      onClick={action.onClick}
    >
      {action.label}
    </button>
  );
}

const telegramLink = (username: string) => `https://t.me/${username.replace(/^@/, '')}`;

function Header({
  conversation,
  name,
  action,
  onMenu,
}: {
  conversation: ConversationOut;
  name: string;
  /** Главное действие диалога (`useActions`): шапка не прокручивается — оно всегда на виду. */
  action: Action | null;
  onMenu: () => void;
}) {
  const { t } = useTranslation('messages');
  const router = useRouter();
  const state = dealState(conversation);
  const profileId = conversation.counterpart_profile_id;
  const person = (
    <>
      <Avatar name={name} size="sm" palette={paletteFor(conversation.counterpart_id)} />
      <span className="flex min-w-0 flex-col">
        {/* имя собеседника — заголовок экрана: размер и вес — как у строки рядом; обрезается
            только очень длинное — «Алексей Морозов» с «Dogovorite se» и «Никола Петрович» с
            «Naruči ponovo» помещаются и при 360 px */}
        <h1 className="m-0 truncate text-[1em] font-semibold">{name}</h1>
        {/* что со сделкой не обрезается: длинное («Договорённость отменена» рядом с кнопкой)
            переносится второй строкой; сделки нет — строки нет, без «Сделки пока нет» (№8) */}
        {state !== 'none' && <span className="text-cap text-text2">{t(`deal.${state}`)}</span>}
      </span>
    </>
  );
  const toProfile = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (profileId) void router.navigate({ to: profilePath(profileId) });
  };

  // слева 12 px, как у ленты под шапкой, и промежутки на 2 px уже, чем на артборде: при 360 px
  // рядом с кнопкой и «⋯» имени нужно 132 px
  return (
    <header
      aria-label={name}
      className="sticky top-0 z-10 flex items-center gap-1.5 border-0 border-b border-solid border-line bg-bg py-2.5 pr-4 pl-3"
    >
      {profileId ? (
        <a
          href={router.history.createHref(profilePath(profileId))}
          onClick={toProfile}
          className="flex min-w-0 flex-1 items-center gap-2 text-text"
        >
          {person}
        </a>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2">{person}</div>
      )}
      {action && (
        <Button
          size="sm"
          variant={action.secondary ? 'secondary' : 'primary'}
          onClick={action.onClick}
          disabled={action.busy}
          aria-busy={action.busy}
          aria-label={action.title}
        >
          {action.label}
        </Button>
      )}
      {conversation.counterpart_name !== null && (
        // на артборде «⋯» — в шапке Telegram, здесь — в своей: прозрачные поля кнопки заходят в
        // промежуток и в отступ до края экрана, чтобы имени и статусу осталось место (зона нажатия
        // — те же 44 × 44)
        <IconButton
          plain
          icon="more"
          label={t('chat.menu')}
          className="-mr-4 -ml-1.5"
          onClick={onMenu}
        />
      )}
    </header>
  );
}

/** Поле ввода со своим черновиком: набор текста перерисовывает только его, а не всю переписку. */
function DraftComposer({
  onSend,
  bottomInset,
}: {
  onSend: (text: string) => void;
  bottomInset: number;
}) {
  const { t } = useTranslation('messages');
  const [draft, setDraft] = useState('');
  return (
    <Composer
      value={draft}
      onChange={setDraft}
      onSend={() => {
        onSend(draft);
        setDraft('');
      }}
      placeholder={t('chat.placeholder')}
      label={t('chat.placeholder')}
      sendLabel={t('chat.send')}
      maxLength={MAX_MESSAGE}
      bottomInset={bottomInset}
    />
  );
}

/** Сообщение ленты: перерисовывается, только когда изменилось оно само (опрос раз в 4 с отдаёт
 *  ту же историю — те же объекты). */
const Entry = memo(function Entry({
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
});

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
  const text = (
    <MaskedText
      text={message.body}
      label={t('mask.text')}
      hiddenLabel={t('mask.label')}
      side={message.mine ? 'out' : 'in'}
    />
  );
  if (message.kind === 'offer') {
    const offer = message.offer;
    const amount = offer?.price_amount;
    const priceType = offer?.price_type;
    const price = offerPrice(format, priceType, amount);
    const when = typeof offer?.availability_note === 'string' ? offer.availability_note : null;
    return (
      <span className="flex flex-col gap-1">
        <span className="text-cap font-semibold opacity-80">{t('chat.offer')}</span>
        {text}
        {price && <span className="font-semibold">{t('chat.offerPrice', { price })}</span>}
        {when && <span>{t('chat.offerWhen', { when })}</span>}
      </span>
    );
  }
  return text;
}

function SystemEvent({
  message,
  conversation,
}: {
  message: MessageOut;
  conversation: ConversationOut;
}) {
  const { t } = useTranslation('messages');
  const format = useFormat();
  const event = message.event;
  if (!event) return null;
  if (event.type === 'deal_agreed')
    return <SystemNote icon="check-circle">{t('chat.event.dealAgreed')}</SystemNote>;
  if (event.type === 'deal_cancelled') {
    // сделки не было — было предложение: его не приняли или оно истекло (№14)
    const text = !event.proposal
      ? t('chat.event.dealCancelled')
      : event.reason === 'expired'
        ? t('chat.event.dealExpired')
        : t('chat.event.dealDeclined');
    return <SystemNote icon="x">{text}</SystemNote>;
  }
  if (event.by !== conversation.my_role) {
    return <SystemNote icon="check">{t('chat.event.dealProposedTheirs')}</SystemNote>;
  }
  // одна строка: условия ушли, кто и до когда отвечает, как узнать о решении
  const until = new Date(Date.parse(message.created_at) + PROPOSAL_TTL_MS);
  return (
    <SystemNote icon="check">
      {t('chat.event.dealProposedMine', {
        name: conversation.counterpart_name ?? t('list.deleted'),
        date: format.calendarGenitive(until),
      })}
    </SystemNote>
  );
}

/** Предложение «Договориться» ждёт ответа 72 ч (deals PROPOSAL_TTL), потом истекает само. */
const PROPOSAL_TTL_MS = 72 * 60 * 60 * 1000;

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

type Row =
  { type: 'day'; key: string; date: Date } | { type: 'entry'; key: string; entry: ChatEntry };

/** Лента с подписями дней: подпись — перед первым сообщением каждого дня после `first` (день, с
 *  которого начат диалог: его подпись — над строкой «Диалог из профиля…»). Ключ подписи — по её
 *  сообщению: «Показать раньше» и новые сообщения не перерисовывают остальные. */
function withDays(entries: readonly ChatEntry[], first: string): Row[] {
  const rows: Row[] = [];
  let day = first;
  for (const entry of entries) {
    const key = entryKey(entry);
    const date = new Date(
      entry.type === 'message' ? entry.message.created_at : entry.pending.createdAt,
    );
    if (dayKey(date) !== day) {
      day = dayKey(date);
      rows.push({ type: 'day', key: `day:${key}`, date });
    }
    rows.push({ type: 'entry', key, entry });
  }
  return rows;
}

/** Диалог до первого ответа — как настоящий: шапка с собеседником, пузыри по низу, поле ввода.
 *  Открыли из списка S29 — собеседник и сделка в шапке из него сразу; кнопки шапки (сделка,
 *  контакты) — только по ответу диалога. */
function Loading({ conversation }: { conversation: ConversationOut | undefined }) {
  const { t } = useTranslation('messages');
  const insets = useInsets();
  const name = conversation ? (conversation.counterpart_name ?? t('list.deleted')) : null;
  return (
    <div aria-busy="true" className="flex min-h-[calc(100dvh-var(--tg-top,0px))] flex-col">
      <div className="flex items-center gap-2 border-0 border-b border-solid border-line bg-bg py-2.5 pr-4 pl-3">
        {conversation && name ? (
          <>
            <Avatar name={name} size="sm" palette={paletteFor(conversation.counterpart_id)} />
            <span className="flex min-w-0 flex-col">
              {/* имя собеседника — заголовок экрана: размер и вес — как у строки рядом */}
              <h1 className="m-0 truncate text-[1em] font-semibold">{name}</h1>
              {dealState(conversation) !== 'none' && (
                <span className="text-cap text-text2">{t(`deal.${dealState(conversation)}`)}</span>
              )}
            </span>
          </>
        ) : (
          <>
            <Skeleton round className="size-9 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col">
              <SkeletonText className="w-2/5" />
              <SkeletonText size="cap" className="w-1/4" />
            </div>
          </>
        )}
      </div>
      <ChatSkeleton />
      <div
        aria-hidden="true"
        className="flex items-end gap-2 border-0 border-t border-solid border-line bg-bg px-2.5 pt-2"
        style={{ paddingBottom: insets.bottom + 8 }}
      >
        <span className="block h-11 flex-1 rounded-[22px] border border-solid border-line bg-bg2" />
        <Skeleton round className="size-11 shrink-0" />
      </div>
    </div>
  );
}
