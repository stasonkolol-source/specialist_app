"""BFF-эндпоинты экранов (ARCHITECTURE §5.2 п. 7): собирают ответ из фасадов нескольких модулей.

Каждый файл views/<экран>.py добавляет свой роутер в `router`.
"""

from fastapi import APIRouter

router = APIRouter()
