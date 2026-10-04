// «Поделиться» (DEVELOPMENT_PLAN 7.4): S08, S10, S15, S21, S23. По нажатию — POST /share: ссылка
// `t.me/<bot>?startapp=…` (у вошедшего — с его кодом `_r`) и, если Telegram принял, карточка для
// `shareMessage` — окно выбора чата с карточкой и кнопкой. Карточки нет или клиент старый —
// ссылка: в Telegram — `t.me/share/url`, в браузере — `navigator.share` или копирование (тост
// «Ссылка скопирована»). Закрытое окно выбора чата второй раз не открываем: ссылкой не дублируем.
import type { ShareOut, ShareTarget } from '@sosed/api-client';
import { getViewsCreateShareMutationKey, viewsCreateShare } from '@sosed/api-client';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

export type ShareOutcome = 'shared' | 'copied' | 'failed';

/** Что нужно от платформы (`@sosed/platform`): хуки её не импортируют. */
export interface ShareChannel {
  readonly capabilities: { readonly shareMessage: boolean };
  shareMessage(preparedMessageId: string): Promise<boolean>;
  shareLink(url: string, text?: string): Promise<ShareOutcome>;
}

/** Сколько висит тост «Ссылка скопирована». */
export const COPIED_TOAST_MS = 2500;

export async function shareVia(channel: ShareChannel, out: ShareOut): Promise<ShareOutcome> {
  if (out.prepared_message_id && channel.capabilities.shareMessage) {
    await channel.shareMessage(out.prepared_message_id);
    return 'shared';
  }
  return channel.shareLink(out.url, out.text);
}

export interface ShareTargetRef {
  type: ShareTarget;
  id: string;
}

export function useShare(channel: ShareChannel) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPIED_TOAST_MS);
    return () => clearTimeout(timer);
  }, [copied]);
  const mutation = useMutation({
    mutationKey: getViewsCreateShareMutationKey(),
    mutationFn: async (target: ShareTargetRef) => {
      const out = await viewsCreateShare({ entity_type: target.type, entity_id: target.id });
      return shareVia(channel, out);
    },
    onSuccess: (outcome) => setCopied(outcome === 'copied'),
  });
  return {
    share: (target: ShareTargetRef) => {
      if (!mutation.isPending) mutation.mutate(target);
    },
    pending: mutation.isPending,
    /** Ссылку не получили (нет сети, сущность скрыли) или не удалось ни поделиться, ни скопировать. */
    failed: mutation.isError || mutation.data === 'failed',
    copied,
  };
}

/** Готовая ссылка для поля «Поделиться в чат» S21: берётся один раз на экран (у вошедшего — с
 *  его кодом), карточка из того же ответа уходит кнопкой «Отправить в чат Telegram». */
export function useShareLink(target: ShareTargetRef | null) {
  return useQuery({
    queryKey: ['share', target?.type, target?.id],
    queryFn: () => viewsCreateShare({ entity_type: target!.type, entity_id: target!.id }),
    enabled: target !== null,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  });
}
