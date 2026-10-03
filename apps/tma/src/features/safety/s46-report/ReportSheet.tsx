// S46 Жалоба (шторка; DEVELOPMENT_PLAN 4.7): одна на все экраны — профиль S08, отзыв S11, заявка
// S15, собеседник S30. «Что случилось?» — причины своего типа объекта, «Подробности» по желанию,
// у профиля и собеседника — «Также заблокировать» (кого я уже заблокировал — без неё); под ними —
// когда модератор рассмотрит: угрозы и запрещённое — в течение часа, остальное — 2 часа, с 08:00
// до 23:00. «Отправить жалобу» — кнопкой в шторке: MainButton Telegram под затемнением осталась бы
// у экрана (экран её прячет, пока шторка открыта). Потом — «Жалоба отправлена» и «Готово».
// Повтор жалобы на тот же объект сервер отдаёт той же жалобой — человек видит то же «отправлена».
import type { ReportReason } from '@sosed/api-client';
import { ApiError } from '@sosed/api-client';
import type { ReportTarget } from '@sosed/hooks';
import {
  MAX_REPORT_COMMENT,
  REPORT_REASONS,
  blockedIds,
  blockedUserOf,
  reportQueue,
  useBlocks,
  useReport,
  useToggleBlock,
} from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { useBackButton } from '@sosed/platform';
import {
  Banner,
  Button,
  Checkbox,
  Field,
  Group,
  RadioGroup,
  RadioRow,
  Sheet,
  Text,
  Textarea,
} from '@sosed/ui-web';
import { useId, useState } from 'react';

type Queue = 'safety' | 'fraud';
const LIMIT = 'reports_limit';

interface Done {
  queue: Queue;
  /** Также заблокировать: получилось, не получилось или не просили. */
  blocked: 'ok' | 'failed' | null;
}

export function ReportSheet({ target, onClose }: { target: ReportTarget; onClose: () => void }) {
  const { t } = useTranslation('safety');
  const report = useReport();
  const toggleBlock = useToggleBlock();
  const blocks = useBlocks();
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [comment, setComment] = useState('');
  const [alsoBlock, setAlsoBlock] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const whyId = useId();
  useBackButton(onClose);

  const userId = target.userId;
  const blockable =
    userId !== undefined &&
    (target.type === 'profile' || target.type === 'user') &&
    !blockedIds(blocks.data).has(userId);
  const busy = report.isPending || toggleBlock.isPending;

  const send = async () => {
    if (reason === null || busy) return;
    const text = comment.trim();
    const filed = await report
      .mutateAsync({
        target_type: target.type,
        target_id: target.id,
        reason,
        comment: text === '' ? null : text,
        conversation_id: target.conversationId ?? null,
      })
      .catch(() => null);
    if (filed === null) return; // ошибка — в баннере
    let blocked: Done['blocked'] = null;
    if (alsoBlock && blockable && userId !== undefined) {
      blocked = await toggleBlock
        .mutateAsync({
          user: blockedUserOf({
            user_id: userId,
            display_name: target.name ?? '',
            profile_id: target.profileId ?? null,
          }),
          on: true,
        })
        .then(() => 'ok' as const)
        .catch(() => 'failed' as const);
    }
    setDone({ queue: filed.queue, blocked });
  };

  if (done) return <Sent done={done} onClose={onClose} />;

  const queue = reason === null ? null : reportQueue(reason);
  const sla = queue === 'safety' ? 'safety' : reason === 'fraud' ? 'fraud' : 'other';
  return (
    <Sheet
      open
      title={t(`report.title.${target.type}`)}
      onClose={onClose}
      closeLabel={t('report.close')}
      footer={
        <Button
          full
          disabled={reason === null || busy}
          aria-busy={busy}
          onClick={() => void send()}
        >
          {t('report.submit')}
        </Button>
      }
    >
      {target.name && (
        <Text variant="sm" secondary className="-mt-2">
          {target.name}
        </Text>
      )}
      <div className="flex flex-col gap-2">
        <p id={whyId} className="m-0 text-sm font-semibold">
          {t('report.why')}
        </p>
        <RadioGroup labelledBy={whyId}>
          <Group className="border border-solid border-line">
            {reasonRows(t, target.type).map(({ value, label }) => (
              <RadioRow
                key={value}
                title={label}
                checked={reason === value}
                onChange={() => setReason(value)}
              />
            ))}
          </Group>
        </RadioGroup>
      </div>
      <Field label={t('report.details')}>
        <Textarea
          value={comment}
          maxLength={MAX_REPORT_COMMENT}
          placeholder={t('report.detailsHint')}
          onChange={(event) => setComment(event.target.value)}
        />
      </Field>
      {blockable && (target.type === 'profile' || target.type === 'user') && (
        <Checkbox checked={alsoBlock} onChange={setAlsoBlock} className="min-h-11 items-center">
          {t(`report.alsoBlock.${target.type}`)}
        </Checkbox>
      )}
      <Text variant="cap" secondary>
        {t(`report.sla.${sla}`)}
      </Text>
      {report.error && (
        <Banner tone="danger" role="alert">
          {problemText(report.error) ?? t('report.error')}
        </Banner>
      )}
    </Sheet>
  );
}

/** «Жалоба отправлена»: когда её рассмотрят и, если просили, что человек заблокирован. */
function Sent({ done, onClose }: { done: Done; onClose: () => void }) {
  const { t } = useTranslation('safety');
  return (
    <Sheet
      open
      title={t('report.doneTitle')}
      onClose={onClose}
      closeLabel={t('report.close')}
      footer={
        <Button full onClick={onClose}>
          {t('report.done')}
        </Button>
      }
    >
      <Banner tone="ok" role="status">
        {t(`report.doneText.${done.queue}`)}
      </Banner>
      {done.blocked === 'ok' && (
        <Banner tone="info" icon="ban" role="status">
          {t('report.doneBlocked')}
        </Banner>
      )}
      {done.blocked === 'failed' && (
        <Banner tone="danger" role="alert">
          {t('report.blockFailed')}
        </Banner>
      )}
    </Sheet>
  );
}

type SafetyT = ReturnType<typeof useTranslation<'safety'>>['t'];

/** Причины типа объекта по порядку с подписями: у каждого типа — свои ключи каталога. */
function reasonRows(
  t: SafetyT,
  type: ReportTarget['type'],
): { value: ReportReason; label: string }[] {
  switch (type) {
    case 'profile':
      return REPORT_REASONS.profile.map((value) => ({
        value,
        label: t(`report.reasons.profile.${value}`),
      }));
    case 'job':
      return REPORT_REASONS.job.map((value) => ({
        value,
        label: t(`report.reasons.job.${value}`),
      }));
    case 'review':
      return REPORT_REASONS.review.map((value) => ({
        value,
        label: t(`report.reasons.review.${value}`),
      }));
    case 'message':
      return REPORT_REASONS.message.map((value) => ({
        value,
        label: t(`report.reasons.message.${value}`),
      }));
    case 'user':
      return REPORT_REASONS.user.map((value) => ({
        value,
        label: t(`report.reasons.user.${value}`),
      }));
  }
}

/** Текст ошибки сервера на языке запроса (лимит жалоб, объект недоступен); сбой — общий. */
function problemText(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status >= 500) return null;
  return error.code === LIMIT || error.status === 404 ? (error.problem.detail ?? null) : null;
}
