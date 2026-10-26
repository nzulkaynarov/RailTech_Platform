"""Таблица маршрутов сверена с контрактом: `x-rt-permissions` каждой операции `eds.yaml` = права зависимости маршрута.

Файл контракта — `packages/contracts/openapi/eds.yaml` (или `EDS_OPENAPI_PATH`). Проверка идёт всегда, без пропусков,
и ловит как расхождение прав, так и маршрут, которого нет в контракте. Доменные маршруты (E3) попадают под ту же
проверку без правок теста.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi.routing import APIRoute

from app.api import health
from app.api.deps import PERMISSIONS_ATTR
from app.api.v1 import ROUTERS
from tests.conftest import ACCESS_SECRET  # noqa: F401  # окружение приложения выставляется при импорте conftest

DEFAULT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi" / "eds.yaml"
CONTRACT = Path(os.environ.get("EDS_OPENAPI_PATH", DEFAULT))


def route_permissions(route: APIRoute) -> tuple[str, ...] | None:
    """Права зависимости `require_permission` маршрута; `None` — маршрут открытый (без неё)."""

    def walk(dependant: Any) -> tuple[str, ...] | None:
        found = getattr(dependant.call, PERMISSIONS_ATTR, None)
        if found is not None:
            return tuple(found)
        for sub in dependant.dependencies:
            result = walk(sub)
            if result is not None:
                return result
        return None

    return walk(route.dependant)


def test_routes_match_contract() -> None:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    checked = 0
    routes = [r for router in (health.router, *ROUTERS) for r in router.routes]
    for route in routes:
        assert isinstance(route, APIRoute)
        path = route.path
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            operation = spec.get("paths", {}).get(path, {}).get(method.lower())
            assert operation is not None, f"{method} {path} есть в сервисе, но нет в eds.yaml"
            declared = operation.get("x-rt-permissions")
            actual = route_permissions(route)
            if operation.get("security") == []:
                assert actual is None, f"{method} {path}: в контракте открытый маршрут, в сервисе проверяются права"
            else:
                assert declared is not None, f"{method} {path}: в eds.yaml нет x-rt-permissions"
                assert actual is not None, f"{method} {path}: в сервисе нет require_permission"
                assert set(actual) == set(declared), f"{method} {path}: права {actual} ≠ контракт {declared}"
            checked += 1
    assert checked >= 3  # /health, обмен, /me


def test_permission_codes_match_contract_enum() -> None:
    from app.security.permissions import KNOWN

    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert set(spec["components"]["schemas"]["EdsPermission"]["enum"]) == KNOWN


def test_every_contract_operation_is_implemented_with_its_operation_id() -> None:
    """Обратная сверка (E3): всё, что описано в eds.yaml, есть в сервисе под тем же `operationId`."""
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    implemented: dict[tuple[str, str], str] = {}
    for router in (health.router, *ROUTERS):
        for route in router.routes:
            assert isinstance(route, APIRoute)
            for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
                implemented[(method.lower(), route.path)] = route.operation_id or route.name
    declared = {
        (method, path): operation["operationId"]
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert implemented == declared
