// «Доступен сегодня до …» (DEVELOPMENT_PLAN 2.10): изменить и сразу обновить кэш профиля — кабинет
// S33 и S38 видят новое состояние без перечитывания. Правила вариантов — @sosed/domain.
import { specialistsSetMyAvailability } from '@sosed/api-client';
import type { AvailabilityHour } from '@sosed/domain';
import { untilTime } from '@sosed/domain';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { myProfileQueryKey } from './profile.ts';

/** Включить «до `hour`» или выключить (null). */
export function useSetAvailability() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (hour: AvailabilityHour | null) =>
      specialistsSetMyAvailability({ until: hour === null ? null : untilTime(hour) }),
    onSuccess: (profile) => queryClient.setQueryData(myProfileQueryKey(), profile),
  });
}
