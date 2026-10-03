// «Договорились?» (S30, прямой диалог; DEVELOPMENT_PLAN 6.4): что делаем, цена и когда — вторая
// сторона увидит их на S53 и подтвердит за 72 ч. Цена и время необязательны; время — не в прошлом
// (сервер ответит 422 текстом ошибки). Кнопка «Предложить» — в шторке: MainButton Telegram под
// шторкой не видна.
import type { DealProposalIn } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import { useProposeDeal } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { Banner, Button, Field, Input, Sheet, Stack, Text } from '@sosed/ui-web';
import type { FormEvent } from 'react';
import { useState } from 'react';

const PARA = 100;
const MAX_TITLE = 120;

export function ProposeSheet({
  open,
  conversationId,
  onClose,
  onProposed,
}: {
  open: boolean;
  conversationId: string;
  onClose: () => void;
  onProposed: () => void;
}) {
  const { t } = useTranslation('messages');
  const { t: common } = useTranslation();
  const propose = useProposeDeal(conversationId);
  const [title, setTitle] = useState('');
  const [price, setPrice] = useState('');
  const [when, setWhen] = useState('');
  const amount = Number(price.replace(/\s/g, ''));
  const ready =
    title.trim().length > 0 && (price === '' || (Number.isFinite(amount) && amount > 0));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || propose.isPending) return;
    const terms: DealProposalIn = { title: title.trim() };
    if (price !== '') {
      terms.price_type = 'fixed';
      terms.price_amount = Math.round(amount * PARA);
    }
    if (when !== '') terms.scheduled_at = new Date(when).toISOString();
    propose.mutate(terms, {
      onSuccess: () => {
        setTitle('');
        setPrice('');
        setWhen('');
        onProposed();
      },
    });
  };

  return (
    <Sheet
      open={open}
      title={t('chat.propose.title')}
      onClose={onClose}
      closeLabel={common('action.close')}
      footer={
        <Button
          full
          type="submit"
          form="propose-deal"
          disabled={!ready || propose.isPending}
          aria-busy={propose.isPending}
        >
          {t('chat.propose.submit')}
        </Button>
      }
    >
      <form id="propose-deal" onSubmit={submit}>
        <Stack gap={12}>
          <Text variant="sm" secondary>
            {t('chat.propose.text')}
          </Text>
          <Field label={t('chat.propose.what')}>
            <Input
              value={title}
              maxLength={MAX_TITLE}
              onChange={(event) => setTitle(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field label={t('chat.propose.price')}>
            <Input
              inputMode="numeric"
              value={price}
              placeholder={t('chat.propose.pricePlaceholder')}
              suffix="RSD"
              onChange={(event) => setPrice(event.target.value.replace(/[^\d\s]/g, ''))}
            />
          </Field>
          <Field label={t('chat.propose.when')}>
            <Input
              type="datetime-local"
              value={when}
              onChange={(event) => setWhen(event.target.value)}
            />
          </Field>
          {propose.error && (
            <Banner tone="danger" role="alert">
              {detailOf(propose.error) ?? common('error.text')}
            </Banner>
          )}
        </Stack>
      </form>
    </Sheet>
  );
}

/** Текст ошибки сервера на языке запроса (условия не прошли, диалог закрыт); сбой — общий. */
function detailOf(error: unknown): string | null {
  return error instanceof ApiError && error.status < 500 ? (error.problem.detail ?? null) : null;
}
