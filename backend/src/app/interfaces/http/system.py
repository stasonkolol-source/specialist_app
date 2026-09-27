"""Служебные маршруты вне `/api/v1`."""

from fastapi import APIRouter

router = APIRouter(include_in_schema=False)


@router.api_route("/up", methods=["GET", "HEAD"])
async def up() -> dict[str, str]:
    """Liveness для kamal-proxy: процесс жив. БД не трогаем — её готовность проверяют
    pre-deploy миграции и pg-smoke, а падение БД не должно перезапускать web."""
    return {"status": "ok"}
