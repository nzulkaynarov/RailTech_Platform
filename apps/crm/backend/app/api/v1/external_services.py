"""«Внешние сервисы» (admin, M3-CRM-12, ADR-0024): реестр, проверки, инциденты, выключатели."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ContainerDep, require
from app.schemas.external_services import (
    ExternalServiceDetailOut,
    ExternalServiceOut,
    ExternalServicesOut,
    ServiceEnableIn,
    ServiceSwitchIn,
)
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1/admin/external-services", tags=["external-services"])

Reader = Annotated[Principal, Depends(require("external_services", "read"))]
Writer = Annotated[Principal, Depends(require("external_services", "write"))]
Key = Annotated[str, Path(max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]


@router.get("", response_model=ExternalServicesOut)
async def list_external_services(_: Reader, container: ContainerDep) -> ExternalServicesOut:
    """Все внешние сервисы ансамбля со статусом, подсказкой «что сделать», метриками и выключателем.

    Только чтение: статус — из последней фоновой проверки (раз в минуту / раз в 15 мин), без
    вызовов моделей. Сервисы ERP — «нет данных», пока ERP не передаёт состояние (M3-ERP-06).
    """
    return await container.external_view.list(datetime.now(UTC))


@router.get("/{key}", response_model=ExternalServiceDetailOut)
async def get_external_service(
    key: Key, _: Reader, container: ContainerDep
) -> ExternalServiceDetailOut:
    """Сервис, его проверки за 24 ч, сводка по дням за 7 дней и инциденты за 30 дней."""
    return await container.external_view.detail(key, datetime.now(UTC))


@router.post("/{key}/check", response_model=ExternalServiceDetailOut)
async def check_external_service(
    key: Key, _: Writer, container: ContainerDep
) -> ExternalServiceDetailOut:
    """Проверить сервис сейчас (включая медленные пробы); инцидент и оповещение — как у фоновой."""
    now = datetime.now(UTC)
    service = await container.external_view.get(key, now)
    if service.source == "crm":
        await container.external_checks.run("manual", now, keys=[key])
        container.external_view.invalidate()
    return await container.external_view.detail(key, datetime.now(UTC))


@router.post("/{key}/disable", response_model=ExternalServiceOut)
async def disable_external_service(
    key: Key, body: ServiceSwitchIn, who: Writer, container: ContainerDep
) -> ExternalServiceOut:
    """Выключить сервис вручную (пароль админа, аудит): вендор — вызовы на запасную модель,
    Langfuse — без трейсов, почта — пауза очереди, Telegram — пауза исходящих.

    Нет выключателя или вендор запасной модели — `409 service_not_switchable`.
    """
    reason = body.reason.strip() if body.reason and body.reason.strip() else None
    await container.external_switches.disable(who, key, body.password.get_secret_value(), reason)
    container.external_view.invalidate()
    return await container.external_view.get(key, datetime.now(UTC))


@router.post("/{key}/enable", response_model=ExternalServiceOut)
async def enable_external_service(
    key: Key, body: ServiceEnableIn, who: Writer, container: ContainerDep
) -> ExternalServiceOut:
    """Включить сервис обратно (пароль админа, аудит); почта отправляет накопленные письма."""
    await container.external_switches.enable(who, key, body.password.get_secret_value())
    container.external_view.invalidate()
    return await container.external_view.get(key, datetime.now(UTC))
