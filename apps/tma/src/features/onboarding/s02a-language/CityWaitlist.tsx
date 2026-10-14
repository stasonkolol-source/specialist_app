// Лист ожидания города «скоро» на S02a: нажали Белград — «Белград скоро. Сообщим, когда
// откроемся» и «Сообщить о запуске». POST /me/city-waitlist включает группу уведомлений
// `city_launch` (как «Вещи» на S58 — `goods_launch`), сервер пишет событие `city_waitlist_joined`
// с городом. Выбор города не меняется: человек остаётся на пилотном (Нови-Сад) и идёт дальше.
// Боту писать, может, ещё нельзя (разрешение спрашивает S02c), поэтому «Готово!» не обещает бот.
import type { CityOut } from '@sosed/api-client';
import {
  getNotificationsGetNotificationSettingsQueryKey,
  useNotificationsJoinCityWaitlist,
} from '@sosed/api-client';
import { useTranslation } from '@sosed/i18n';
import { Banner, Button, Card, Text } from '@sosed/ui-web';
import { useQueryClient } from '@tanstack/react-query';

export function CityWaitlist({ city }: { city: CityOut }) {
  const { t } = useTranslation('onboarding');
  const queryClient = useQueryClient();
  const join = useNotificationsJoinCityWaitlist({
    mutation: {
      // ответ — настройки уведомлений целиком: S43 покажет переключатель без перечитывания
      onSuccess: (settings) =>
        queryClient.setQueryData(getNotificationsGetNotificationSettingsQueryKey(), settings),
    },
  });
  const busy = join.isPending;
  return (
    <Card className="flex flex-col gap-3">
      <Text variant="sm">{t('city.waitlist.text', { city: city.name })}</Text>
      {join.isSuccess ? (
        <Banner tone="ok" role="status">
          {t('city.waitlist.done', { city: city.name })}
        </Banner>
      ) : (
        <Button
          full
          variant="secondary"
          icon="bell"
          onClick={() => join.mutate({ data: { city_id: city.id } })}
          disabled={busy}
          aria-busy={busy}
        >
          {t('city.waitlist.notify')}
        </Button>
      )}
      {join.isError && (
        <p role="alert" className="m-0 text-center text-cap text-danger">
          {t('city.waitlist.error')}
        </p>
      )}
    </Card>
  );
}
