"""Ошибки BFF соответствуют схеме Error контракта."""

from typing import Any

import httpx
import jsonschema
from fastapi import FastAPI

from app.errors import PlatformError


def validate_error(contract: dict[str, Any], body: object) -> None:
    schema = contract["components"]["schemas"]["Error"]
    jsonschema.Draft202012Validator(schema).validate(body)


async def test_unknown_route_is_not_found_error(
    client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    validate_error(contract, body)
    assert body["code"] == "NOT_FOUND"
    assert body["source"] == "bff"


async def test_platform_error_keeps_source_and_details(
    app: FastAPI, client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise PlatformError(
            "BACKEND_UNAVAILABLE",
            "ERP не отвечает.",
            status_code=503,
            source="erp",
            details={"backend_code": "timeout"},
        )

    response = await client.get("/api/v1/_boom")
    assert response.status_code == 503
    body = response.json()
    validate_error(contract, body)
    assert body == {
        "code": "BACKEND_UNAVAILABLE",
        "message": "ERP не отвечает.",
        "source": "erp",
        "details": {"backend_code": "timeout"},
    }


async def test_validation_error_lists_fields(
    app: FastAPI, client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    @app.get("/api/v1/_needs_int")
    async def needs_int(n: int) -> int:
        return n

    response = await client.get("/api/v1/_needs_int", params={"n": "x"})
    assert response.status_code == 422
    body = response.json()
    validate_error(contract, body)
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["fields"] == ["query.n"]


async def test_unhandled_exception_is_internal_error(
    app: FastAPI, client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    @app.get("/api/v1/_crash")
    async def crash() -> None:
        raise RuntimeError("secret internals")

    response = await client.get("/api/v1/_crash")
    assert response.status_code == 500
    body = response.json()
    validate_error(contract, body)
    assert "secret" not in response.text


async def test_method_not_allowed_is_neutral_4xx_code(
    client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    response = await client.post("/api/v1/health")
    assert response.status_code == 405
    body = response.json()
    validate_error(contract, body)
    assert body["code"] == "METHOD_NOT_ALLOWED"


async def test_unlisted_4xx_gets_status_code(
    app: FastAPI, client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    from fastapi import HTTPException

    @app.get("/api/v1/_teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418)

    response = await client.get("/api/v1/_teapot")
    assert response.status_code == 418
    body = response.json()
    validate_error(contract, body)
    assert body["code"] == "HTTP_418"
