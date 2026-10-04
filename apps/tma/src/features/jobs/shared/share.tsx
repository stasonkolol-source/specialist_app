// «Поделиться» заявкой (DEVELOPMENT_PLAN 7.4): S15, S21, S23. Логика — useShare (@sosed/hooks):
// карточка в выбор чата Telegram или ссылка; здесь — тост «Ссылка скопирована» и сообщение об
// ошибке над таббаром. Делятся только тем, что видит гость: опубликованной заявкой не прямым
// запросом — остальное сервер не отдаёт.
import type { JobOut } from '@sosed/api-client';
import { useShare } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Toast } from '@sosed/ui-web';
import { useEffect, useState } from 'react';

/** Заявку видит любой — ею можно поделиться. */
export function shareable(job: Pick<JobOut, 'status' | 'visibility'>): boolean {
  return job.status === 'published' && job.visibility === 'public';
}

export function useJobShare(jobId: string) {
  const { t } = useTranslation();
  const platform = usePlatform();
  const { share, pending, failed, copied } = useShare(platform);
  const [linkCopied, setLinkCopied] = useState(false);
  useEffect(() => {
    if (!linkCopied) return;
    const timer = setTimeout(() => setLinkCopied(false), 2500);
    return () => clearTimeout(timer);
  }, [linkCopied]);
  let notice = null;
  if (copied || linkCopied) notice = <Toast icon="link">{t('share.copied')}</Toast>;
  else if (failed) notice = <Toast icon="alert">{t('share.failed')}</Toast>;
  return {
    share: () => share({ type: 'job', id: jobId }),
    /** Скопировать готовую ссылку (поле S21). */
    copy: (url: string) => {
      void navigator.clipboard?.writeText(url).then(
        () => setLinkCopied(true),
        () => undefined,
      );
    },
    pending,
    notice,
  };
}
