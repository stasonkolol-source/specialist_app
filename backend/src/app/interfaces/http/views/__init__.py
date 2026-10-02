"""BFF-эндпоинты экранов (ARCHITECTURE §5.2 п. 7): собирают ответ из фасадов нескольких модулей.

Каждый файл views/<экран>.py добавляет свой роутер в `router`.
"""

from fastapi import APIRouter

router = APIRouter()

from app.interfaces.http.views import my_job, specialist  # noqa: E402 — роутеры экранов ниже router

router.include_router(specialist.router)
router.include_router(my_job.router)
