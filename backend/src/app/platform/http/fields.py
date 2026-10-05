"""Общие поля входа API (QA ADV-01, ADV-03, ADV-04): числа — в границах колонок, текст — чистый.

- id справочников (город, район, категория) в БД — integer: число больше 2^31 − 1 — 422
  `validation_error` до запроса, а не DataError базы (500). Ноль и меньше — тоже 422.
- Суммы и размеры в БД — bigint: где у домена своей границы нет, держим `BIGINT_MAX`.
- Свободный текст — `CleanText`: без NUL и управляющих символов и без невидимых
  (`platform/text/clean.py`) до проверок длины схемы и домена, поэтому «не пусто» и
  минимальная длина считают видимые символы; пробелы по краям обрезает домен, как и раньше.
"""

from typing import Annotated, Final

from pydantic import BeforeValidator, Field

from app.platform.kernel.ids import CategoryId, CityId, DistrictId
from app.platform.text.clean import clean_text

INT4_MAX: Final = 2**31 - 1
BIGINT_MAX: Final = 2**63 - 1

CityIdIn = Annotated[CityId, Field(ge=1, le=INT4_MAX)]
DistrictIdIn = Annotated[DistrictId, Field(ge=1, le=INT4_MAX)]
CategoryIdIn = Annotated[CategoryId, Field(ge=1, le=INT4_MAX)]


def _clean(value: object) -> object:
    # не строку не трогаем: тип поля сам ответит 422 на число или список
    return clean_text(value) if isinstance(value, str) else value


_CLEAN = BeforeValidator(_clean)
CleanText = Annotated[str, _CLEAN]
"""Свободный текст с клиента: заголовок, сообщение, отзыв, подпись, комментарий."""
OptionalCleanText = Annotated[str | None, _CLEAN]
"""То же, необязательное. Не `OptionalCleanText`: тогда `min_length` и `max_length` поля pydantic
проверяет отдельным шагом с другим кодом ошибки (`too_long` вместо `string_too_long`)."""
