"""operationId по правилу ADR-0020 §10: `<модуль>_<имя функции роутера>`.

Из него orval делает имена хуков (`jobs_close_job` → `useJobsCloseJob`), поэтому имя
выводится из места, где лежит обработчик, а не пишется руками.
"""

import re

from fastapi.routing import APIRoute

_MODULE_ROUTER = re.compile(r"app\.modules\.(?P<module>[a-z_]+)\.http(?:\.|$)")


def operation_id(route: APIRoute) -> str:
    owner = _owner(route.endpoint.__module__)
    if owner is None:
        raise ValueError(
            f"route {route.path}: handler {route.endpoint.__module__}.{route.name} must live in"
            " app/modules/<module>/http or app/interfaces/http"
        )
    return f"{owner}_{route.name}"


def _owner(module: str) -> str | None:
    if match := _MODULE_ROUTER.match(module):
        return match["module"]
    if module == "app.interfaces.http.views" or module.startswith("app.interfaces.http.views."):
        return "views"
    if module.startswith("app.interfaces.http."):
        return "system"
    return None
