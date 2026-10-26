"""Право на каждый эндпоинт (pg), по `x-rt-permissions` eds.yaml: без токена 401, без права 403, с правом — пускает."""

import itertools

import httpx
import pytest

from app.container import Container
from app.security.access_token import issue_access_token
from tests.conftest import ACCESS_SECRET
from tests.domain import SPEC
from tests.helpers import bearer, seed_employee

pytestmark = pytest.mark.pg

GHOST = "00000000-0000-4000-8000-000000000001"
METHODS = ("get", "post")


def operations() -> list[tuple[str, str, list[str]]]:
    """(метод, путь, права) всех защищённых операций контракта."""
    found = []
    for path, item in SPEC["paths"].items():
        for method in METHODS:
            operation = item.get(method)
            if operation is not None and operation.get("security") != []:
                found.append((method, path, operation["x-rt-permissions"]))
    return found


OPS = operations()


def concrete(path: str) -> str:
    return (
        path.replace("{letter_id}", GHOST)
        .replace("{document_id}", GHOST)
        .replace("{approval_id}", GHOST)
        .replace("{file_id}", GHOST)
    )


async def call(client: httpx.AsyncClient, method: str, path: str, headers: dict[str, str]) -> httpx.Response:
    if method == "get":
        return await client.get(concrete(path), headers=headers)
    return await client.post(concrete(path), json={}, headers=headers)


def test_contract_has_the_expected_protected_operations() -> None:
    assert len(OPS) >= 18  # не пустая сверка: письма, документы, маршруты, реестр, файлы, /me


@pytest.mark.parametrize(("method", "path", "codes"), OPS, ids=[f"{m} {p}" for m, p, _ in OPS])
async def test_operation_requires_token_and_one_of_the_listed_permissions(
    client: httpx.AsyncClient, container: Container, method: str, path: str, codes: list[str]
) -> None:
    ids = itertools.count(100)
    assert (await call(client, method, path, {})).status_code == 401

    nobody = next(ids)
    await seed_employee(container, nobody, permissions={"eds": []})
    headers = bearer(issue_access_token(nobody, ACCESS_SECRET))
    denied = await call(client, method, path, headers)
    if codes:  # пустой список (/me) — любой активный сотрудник
        assert denied.status_code == 403, denied.text
        assert denied.json()["code"] == "FORBIDDEN"
    else:
        assert denied.status_code == 200

    # право, которого в списке нет, не помогает
    all_codes: set[str] = set(SPEC["components"]["schemas"]["EdsPermission"]["enum"])
    for other in sorted(all_codes - set(codes))[:2] if codes else []:
        outsider = next(ids)
        await seed_employee(container, outsider, permissions={"eds": [other]})
        response = await call(client, method, path, bearer(issue_access_token(outsider, ACCESS_SECRET)))
        assert response.status_code == 403, f"{other} не должно открывать {method} {path}"

    for code in codes:
        holder = next(ids)
        await seed_employee(container, holder, permissions={"eds": [code]})
        response = await call(client, method, path, bearer(issue_access_token(holder, ACCESS_SECRET)))
        assert response.status_code not in (401, 403), (
            f"{code}: {method} {path} → {response.status_code} {response.text}"
        )


async def test_revoked_permission_takes_effect_on_the_next_request(
    client: httpx.AsyncClient, container: Container
) -> None:
    await seed_employee(container, 7, permissions={"eds": ["letters.read"]})
    headers = bearer(issue_access_token(7, ACCESS_SECRET))
    assert (await client.get("/api/v1/letters", headers=headers)).status_code == 200
    later = "2026-10-27T08:00:00Z"  # снимок CRM новее прежнего — отзыв применяется
    await seed_employee(container, 7, permissions={"eds": []}, updated_at=later)
    assert (await client.get("/api/v1/letters", headers=headers)).status_code == 403
