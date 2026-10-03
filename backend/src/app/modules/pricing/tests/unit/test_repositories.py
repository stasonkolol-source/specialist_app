"""Ошибки сохранения прайса: неизвестная категория — ошибка поля, а не сбой сервера."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.domain.service import PriceType, Service
from app.modules.pricing.errors import InvalidServiceError
from app.modules.pricing.infrastructure.models import ServiceRow
from app.modules.pricing.infrastructure.repositories import SqlServiceRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, new_id

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("operation", ["add", "save"])
@pytest.mark.parametrize(
    "constraint", ["fk_services_category_id_categories", "fk_services_profile_id_profiles"]
)
async def test_only_missing_category_becomes_a_field_error(operation: str, constraint: str) -> None:
    service = Service.add(
        profile_id=new_id(),
        title="Замена розетки",
        price_type=PriceType.FIXED,
        price_min=150_000,
        category_id=CategoryId(2**31 - 1),
        position=0,
        now=datetime(2026, 10, 3, tzinfo=UTC),
    )
    original = Exception("Нарушен внешний ключ")
    original.diag = SimpleNamespace(constraint_name=constraint)  # type: ignore[attr-defined]
    failure = IntegrityError("INSERT / UPDATE pricing.services", {}, original)
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = ServiceRow(id=service.id)
    session.flush.side_effect = failure
    uow = Mock(spec=UnitOfWork)
    repository = SqlServiceRepository(session, uow)
    write = repository.add if operation == "add" else repository.save

    if constraint == "fk_services_category_id_categories":
        with pytest.raises(InvalidServiceError) as caught:
            await write(service)
        assert caught.value.params == {"field": "category_id"}
        assert caught.value.__cause__ is failure
    else:
        with pytest.raises(IntegrityError) as unhandled:
            await write(service)
        assert unhandled.value is failure
    uow.track.assert_not_called()
