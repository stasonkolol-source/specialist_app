"""BFF-эндпоинты экранов (ARCHITECTURE §5.2 п. 7): собирают ответ из фасадов нескольких модулей.

Каждый файл views/<экран>.py добавляет свой роутер в `router`.
"""

from fastapi import APIRouter

router = APIRouter()

from app.interfaces.http.views import (  # noqa: E402 — роутеры экранов ниже router
    badges,
    blocks,
    deal,
    history,
    my_job,
    share,
    specialist,
)

router.include_router(specialist.router)
router.include_router(my_job.router)
router.include_router(badges.router)
router.include_router(deal.router)
router.include_router(history.router)
router.include_router(blocks.router)
router.include_router(share.router)
