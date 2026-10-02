"""Шаблон отклика (DEVELOPMENT_PLAN 5.5): название от 1 до 40 знаков без крайних пробелов, первый
по порядку — основной."""

import pytest

from app.modules.jobs.domain.response import Offer, ResponsePriceType
from app.modules.jobs.domain.template import (
    MAX_TEMPLATE_TITLE,
    ResponseTemplate,
    TemplateId,
    template_title,
)
from app.modules.jobs.errors import InvalidTemplateError
from app.modules.jobs.tests.builders import NOW
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit


def test_title_is_trimmed_and_limited() -> None:
    assert template_title("  Могу сегодня ") == "Могу сегодня"
    assert template_title("я" * MAX_TEMPLATE_TITLE) == "я" * MAX_TEMPLATE_TITLE


@pytest.mark.parametrize("title", ["", "   ", "я" * (MAX_TEMPLATE_TITLE + 1)])
def test_empty_or_long_title_is_refused(title: str) -> None:
    with pytest.raises(InvalidTemplateError) as error:
        template_title(title)
    assert error.value.params == {"field": "title", "reason": "length"}


@pytest.mark.parametrize(("position", "primary"), [(0, True), (1, False)])
def test_the_first_template_is_primary(position: int, primary: bool) -> None:
    template = ResponseTemplate(
        id=TemplateId(new_id()),
        user_id=UserId(new_id()),
        title="Могу сегодня",
        offer=Offer(message="Могу сегодня.", price_type=ResponsePriceType.NEGOTIABLE),
        position=position,
        created_at=NOW,
        updated_at=NOW,
    )
    assert template.primary is primary
