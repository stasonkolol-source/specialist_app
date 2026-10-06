// Поля предложения исполнителя: сообщение клиенту, цена «Фикс / От / За час / Договорная» и «когда
// смогу» — форма отклика S16 и шаблон S57 (DEVELOPMENT_PLAN 5.5). Ошибки — после первой попытки
// отправить: пустое сообщение, цена без суммы.
import type { ResponsePriceType } from '@sosed/api-client';
import type { OfferDraft, OfferProblem } from '@sosed/hooks';
import {
  RESPONSE_AVAILABILITY_MAX,
  RESPONSE_MESSAGE_MAX,
  RESPONSE_PRICE_TYPES,
} from '@sosed/hooks';
import { moneyInput, useLocale, useTranslation } from '@sosed/i18n';
import { Icon, Input, Segmented, Text, Textarea } from '@sosed/ui-web';
import type { ReactNode } from 'react';
import { useId } from 'react';

export interface OfferFieldsProps {
  draft: OfferDraft;
  onChange: (patch: Partial<OfferDraft>) => void;
  problems: readonly OfferProblem[];
  /** Справа от подписи сообщения: «Мои шаблоны» на S16. */
  messageAction?: ReactNode;
  /** Под сообщением: чипы шаблонов на S16. */
  messageExtra?: ReactNode;
}

export function OfferFields({
  draft,
  onChange,
  problems,
  messageAction,
  messageExtra,
}: OfferFieldsProps) {
  const { t } = useTranslation('jobs');
  const locale = useLocale();
  const messageId = useId();
  const messageError = useId();
  const amountError = useId();
  const whenId = useId();
  const whenHint = useId();
  const noMessage = problems.includes('message');
  const noAmount = problems.includes('amount');
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <div className="flex min-h-11 items-center justify-between gap-3">
          <label htmlFor={messageId} className="text-sm font-semibold">
            {t('respond.message')}
          </label>
          {messageAction}
        </div>
        <Textarea
          id={messageId}
          rows={3}
          maxLength={RESPONSE_MESSAGE_MAX}
          value={draft.message}
          placeholder={t('respond.messagePlaceholder')}
          invalid={noMessage}
          aria-describedby={noMessage ? messageError : undefined}
          onChange={(event) => onChange({ message: event.target.value })}
        />
        {noMessage && (
          <p id={messageError} className="m-0 text-cap text-danger">
            {t('respond.missingMessage')}
          </p>
        )}
        {messageExtra}
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-semibold">{t('respond.price')}</span>
        <Segmented<ResponsePriceType>
          label={t('respond.price')}
          value={draft.priceType}
          onChange={(priceType) => onChange({ priceType })}
          options={RESPONSE_PRICE_TYPES.map((type) => ({
            value: type,
            label: t(`respond.priceTypes.${type}`),
          }))}
        />
        {draft.priceType === 'negotiable' ? (
          <Text secondary>{t('respond.negotiableHint')}</Text>
        ) : (
          <>
            <Input
              inputMode="numeric"
              value={moneyInput(draft.amount, locale)}
              suffix={t('respond.currency')}
              aria-label={t('respond.amount')}
              invalid={noAmount}
              aria-describedby={noAmount ? amountError : undefined}
              onChange={(event) => onChange({ amount: moneyInput(event.target.value, locale) })}
            />
            {noAmount && (
              <p id={amountError} className="m-0 text-cap text-danger">
                {t('respond.missingAmount')}
              </p>
            )}
          </>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={whenId} className="text-sm font-semibold">
          {t('respond.when')}
        </label>
        <Input
          id={whenId}
          icon="calendar"
          maxLength={RESPONSE_AVAILABILITY_MAX}
          value={draft.when}
          placeholder={t('respond.whenPlaceholder')}
          aria-describedby={whenHint}
          onChange={(event) => onChange({ when: event.target.value })}
        />
        <p id={whenHint} className="m-0 flex items-center gap-1.5 text-cap text-text2">
          <Icon name="lock" size={16} className="shrink-0" />
          {t('respond.contacts')}
        </p>
      </div>
    </>
  );
}
