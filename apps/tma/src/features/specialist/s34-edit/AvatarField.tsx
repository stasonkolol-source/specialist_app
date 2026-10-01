// Фото профиля на S34 (DEVELOPMENT_PLAN 2.11): «Изменить фото» — файл с назначением avatar тем же
// загрузчиком, что портфолио, затем PUT /me/profile/avatar; прежнее фото сервер удаляет сам. Пока
// сервер обрабатывает фото (2.2), в кружке — превью с устройства; обработал — профиль
// перечитывается с вариантами. Без фото — инициалы. Фото меняется сразу, без «Сохранить».
import type { ProfileOut } from '@sosed/api-client';
import { specialistsSetMyAvatar } from '@sosed/api-client';
import { myProfileQueryKey, useMediaUploads } from '@sosed/hooks';
import { useTranslation } from '@sosed/i18n';
import { usePlatform } from '@sosed/platform';
import { Avatar, Button, cx } from '@sosed/ui-web';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { ChangeEvent } from 'react';
import { useEffect, useRef } from 'react';

import { useUploadGuard } from '../shared/leave.ts';
import { mediaTransport } from '../shared/uploads.ts';

/** Статусы файла после обработки: дальше он не изменится. */
const SETTLED = new Set(['ready', 'failed', 'rejected']);

export function AvatarField({ profile }: { profile: ProfileOut }) {
  const { t } = useTranslation('specialist');
  const platform = usePlatform();
  const queryClient = useQueryClient();
  const uploads = useMediaUploads({ purpose: 'avatar', transport: mediaTransport });
  const { forget, remove } = uploads;
  // «Сохранить» и «Назад» уводят с S34: фото, которое ещё грузится, остановилось бы
  useUploadGuard(uploads.uploading);
  const input = useRef<HTMLInputElement>(null);
  // файл, уже отправленный в профиль, и файл, после обработки которого профиль перечитан
  const sent = useRef<string | null>(null);
  const refreshed = useRef<string | null>(null);
  const item = uploads.items.at(-1);
  const set = useMutation({
    mutationFn: (mediaId: string) => specialistsSetMyAvatar({ media_id: mediaId }),
    onSuccess: (saved) => queryClient.setQueryData(myProfileQueryKey(), saved),
  });
  const { mutate, reset } = set;
  const avatar = profile.avatar;
  const uploaded = item?.status === 'uploaded' ? item.media : null;

  // загрузилось — сразу в профиль
  useEffect(() => {
    if (!uploaded || sent.current === uploaded.id) return;
    sent.current = uploaded.id;
    mutate(uploaded.id);
  }, [mutate, uploaded]);

  // обработка закончилась — перечитать профиль (варианты или отказ); фото с сервера на месте —
  // превью больше не нужно
  useEffect(() => {
    const media = item?.media;
    if (!item || !media || !set.isSuccess) return;
    if (avatar?.id === media.id && avatar.status === 'ready') forget(item.key);
    else if (SETTLED.has(media.status) && refreshed.current !== media.id) {
      refreshed.current = media.id;
      void queryClient.invalidateQueries({ queryKey: myProfileQueryKey() });
    }
  }, [avatar, forget, item, queryClient, set.isSuccess]);

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // то же фото, выбранное снова, иначе не даст change
    event.target.value = '';
    if (!file) return;
    platform.haptics.selection();
    // прежний выбор: уже фото профиля — забыть, остальное (упало, не отправлено) — удалить
    for (const old of uploads.items) {
      if (old.media && old.media.id === sent.current) forget(old.key);
      else remove(old.key);
    }
    reset();
    uploads.add([file]);
  };

  const busy = uploads.uploading || set.isPending;
  const failed = item?.status === 'failed' || set.isError;
  const caption =
    item?.status === 'uploading'
      ? t('avatar.uploading', { percent: Math.round(item.progress * 100) })
      : failed
        ? t('avatar.failed')
        : t(avatar || item ? 'avatar.own' : 'avatar.initials');

  return (
    <section aria-label={t('avatar.label')} className="flex items-center gap-3">
      <Avatar
        name={profile.display_name}
        src={avatar?.status === 'ready' ? avatar.variants[0]?.url : undefined}
        file={item?.preview}
      />
      <span className={cx('min-w-0 flex-1 text-cap', failed ? 'text-danger' : 'text-text2')}>
        {caption}
      </span>
      <Button
        variant="secondary"
        size="sm"
        icon="camera"
        disabled={busy}
        aria-busy={busy}
        onClick={() => input.current?.click()}
      >
        {t('avatar.change')}
      </Button>
      <input ref={input} type="file" accept="image/*" hidden tabIndex={-1} onChange={pick} />
    </section>
  );
}
