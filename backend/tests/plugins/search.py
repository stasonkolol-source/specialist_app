"""Исполнитель с опубликованным профилем и его строка в read-model поиска (тесты 4.1)."""

from datetime import datetime
from typing import Any

from dishka import AsyncContainer
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.identity.api import IdentityApi, RestrictionIn, RestrictionKind
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.domain.service import PriceType
from app.modules.search.application.use_cases.flush_index import FlushIndex, FlushIndexCommand
from app.modules.specialists.api import SpecialistsApi
from app.modules.specialists.application.use_cases.create_profile import (
    CreateProfile,
    CreateProfileCommand,
)
from app.modules.specialists.application.use_cases.edit_profile import (
    EditProfile,
    EditProfileCommand,
)
from app.modules.specialists.application.use_cases.set_profile_areas import (
    SetProfileAreas,
    SetProfileAreasCommand,
)
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
    SetProfileCategoriesCommand,
)
from app.modules.specialists.application.use_cases.submit_profile import (
    SubmitProfile,
    SubmitProfileCommand,
)
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, CategoryId, CityId, DistrictId, UserId, new_id
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

NAME = "Marko Petrović"
PRICE = 150_000


class Specialist:
    """Исполнитель с опубликованным профилем «Электрик» и его строка в read-model."""

    def __init__(self, container: AsyncContainer) -> None:
        self.container = container
        self.user_id = UserId(new_id())
        self.profile_id = new_id()
        self.city, self.district, self.category = CityId(0), DistrictId(0), CategoryId(0)

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def call(self, use_case: type[Any], command: object) -> Any:
        async with self.container() as request:
            return await (await request.get(use_case))(command)

    async def publish(self, kind: ProfileKind = ProfileKind.PRO) -> None:
        self.city = CityId(await self.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'"))
        self.district = DistrictId(
            await self.scalar("SELECT min(id) FROM geo.districts WHERE city_id = :c", c=self.city)
        )
        self.category = CategoryId(
            await self.scalar("SELECT id FROM catalog.categories WHERE slug = 'electrical'")
        )
        async with self.container() as request:
            session = await request.get(AsyncSession)
            self.user_id = await insert_user(session)
            await accept_rules(session, self.user_id)
        actor = self.user_id
        created = await self.call(
            CreateProfile,
            CreateProfileCommand(actor_id=actor, kind=kind, city_id=self.city, display_name=NAME),
        )
        self.profile_id = created.id
        await self.call(
            EditProfile,
            EditProfileCommand(
                actor_id=actor, headline="Электрик, 10 лет", work_modes=["at_client"]
            ),
        )
        await self.call(
            SetProfileCategories,
            SetProfileCategoriesCommand(actor_id=actor, category_ids=[self.category]),
        )
        await self.call(
            SetProfileAreas, SetProfileAreasCommand(actor_id=actor, district_ids=[self.district])
        )
        await self.call(
            AddService,
            AddServiceCommand(
                actor_id=actor,
                title="Montaža lustera",
                price_type=PriceType.FROM,
                price_min=PRICE,
                category_id=self.category,
            ),
        )
        await self.call(SubmitProfile, SubmitProfileCommand(actor_id=actor))
        async with self.container() as request:
            uow, specialists = await request.get(UnitOfWork), await request.get(SpecialistsApi)
            async with uow:
                await specialists.approve_profile(self.profile_id, version=None)

    async def handle(self, task: str) -> None:
        """Подписчик search отрабатывает событие, затем пересборка — как у воркера."""
        assert await run_queued(self.container, task, user_id=self.user_id) == 1, task
        await self.flush()

    async def flush(self) -> None:
        while (await self.call(FlushIndex, FlushIndexCommand())).more:
            pass

    async def row(self) -> RowMapping | None:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM search.specialist_index WHERE profile_id = :id"),
                {"id": self.profile_id},
            )
            return result.mappings().one_or_none()

    async def matches(self, query: str) -> bool:
        return bool(
            await self.scalar(
                "SELECT search_vector @@ platform.q_all(:q) FROM search.specialist_index"
                " WHERE profile_id = :id",
                q=query,
                id=self.profile_id,
            )
        )

    async def restrict(self, kind: RestrictionKind, until: datetime | None) -> CaseId:
        case_id = CaseId(new_id())
        async with self.container() as request:
            uow, identity = await request.get(UnitOfWork), await request.get(IdentityApi)
            async with uow:
                await identity.restrict(
                    RestrictionIn(
                        user_id=self.user_id,
                        kind=kind,
                        reason_code="spam",
                        ends_at=until,
                        case_id=case_id,
                    )
                )
        return case_id

    async def lift(self, case_id: CaseId) -> None:
        async with self.container() as request:
            uow, identity = await request.get(UnitOfWork), await request.get(IdentityApi)
            async with uow:
                assert await identity.lift_case_restrictions(case_id) == 1

    async def drop_jobs(self) -> None:
        """Чужие подписчики (уведомления, модерация, удаление) тест не выполняет."""
        await self.execute(
            "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
            " args->'payload'->>'user_id' = :user OR args->'payload'->>'author_id' = :user"
            " OR args->'payload'->>'owner_id' = :user"
            " OR args->'payload'->'profile_ids' @> jsonb_build_array(CAST(:profile AS text)))",
            user=str(self.user_id),
            profile=str(self.profile_id),
        )
