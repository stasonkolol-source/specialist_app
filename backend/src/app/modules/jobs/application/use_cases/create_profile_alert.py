"""Подписка из профиля (задача `jobs.create_profile_alert` по ProfilePublished одобренного
профиля; DEVELOPMENT_PLAN 5.7).

Исполнитель не получал заявок, пока сам не заводил подписку на S19, — а туда доходили немногие.
Теперь при первой публикации профиля («Специалист» и «Подработка» одинаково) jobs заводит ему
подписку «сразу» по категориям профиля и его районам выезда (все кварталы города — весь город;
бюджет, срочность и язык — любые), только если своих подписок у него ещё нет: кто уже настроил
их сам, тому ничего не меняем. Поэтому повторная публикация (переход «Подработка → Специалист»,
возврат после отказа) ничего не дублирует. Профиль — через фасад specialists; к моменту задачи
он скрыт или снят — ничего. Категории, которые с тех пор выключили или запретили, пропускаются;
без категорий подписка не нужна. Дальше — как у любой новой подписки: AlertCreated, досыл
открытых заявок последних дней (`jobs.catch_up_alert`), `alert_created` в аналитику с `auto`.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.catalog.api import CatalogApi, RiskLevel
from app.modules.geo.api import GeoApi
from app.modules.jobs.application.alerts import alert_created
from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.domain.alert import AlertCriteria, AlertDelivery, AlertId, JobAlert
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProfileAlertCommand:
    user_id: UserId
    profile_id: UUID


class CreateProfileAlert:
    def __init__(
        self,
        uow: UnitOfWork,
        alerts: JobAlerts,
        specialists: SpecialistsApi,
        catalog: CatalogApi,
        geo: GeoApi,
        clock: Clock,
    ) -> None:
        self._uow, self._alerts, self._specialists = uow, alerts, specialists
        self._catalog, self._geo, self._clock = catalog, geo, clock

    async def __call__(self, cmd: CreateProfileAlertCommand) -> JobAlert | None:
        """Созданная подписка; None — у исполнителя уже есть свои или подписывать не на что."""
        if await self._alerts.of_user(cmd.user_id):
            return None
        profile = await self._specialists.public_profile(cmd.profile_id)
        if profile is None or profile.user_id != cmd.user_id:
            return None
        categories = tuple(
            category.id
            for category in await self._catalog.categories(profile.category_ids)
            if category.is_active and category.risk_level < RiskLevel.FORBIDDEN
        )
        if not categories:
            return None
        districts = profile.area_ids
        if districts and await self._geo.covers_city(profile.city_id, districts):
            districts = ()
        criteria = AlertCriteria(
            category_ids=categories, city_id=profile.city_id, district_ids=districts
        )
        now = self._clock.now()
        async with self._uow:
            await self._alerts.lock(cmd.user_id)
            if await self._alerts.of_user(cmd.user_id):  # успел завести сам, пока задача ждала
                return None
            alert = JobAlert(
                id=AlertId(new_id()),
                user_id=cmd.user_id,
                criteria=criteria,
                delivery=AlertDelivery.INSTANT,
                is_active=True,
                paused_until=None,
                created_at=now,
                updated_at=now,
            )
            await self._alerts.add(alert)
            self._uow.add_event(alert_created(alert, auto=True))
        return alert
