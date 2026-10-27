"""«Модели ИИ» — смена провайдера, модели и ключа роли из CRM (admin, ADR-0020).

Повторный пароль обязателен; ключ уходит только в LiteLLM, в ответах — нет. Платная проверка
качества после смены не запускается сама — только рекомендация в ответе.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import ContainerDep, require
from app.integrations.litellm_admin import LiteLLMAdmin, load_defaults
from app.schemas.spend import (
    ModelChangeIn,
    ModelChangeResult,
    ModelResetIn,
    ProviderKeyIn,
    ProviderKeyResult,
)
from app.security.principal import Principal
from app.security.reauth import LockoutPolicy
from app.services.models_admin import ModelChange, ModelsAdminService

router = APIRouter(prefix="/api/v1/models", tags=["spend"])

Writer = Annotated[Principal, Depends(require("models", "write"))]
Alias = Annotated[str, Path(max_length=64)]


def get_service(request: Request, container: ContainerDep) -> ModelsAdminService:
    """Клиент LiteLLM тесты подменяют через `app.state.litellm_admin`."""
    settings = container.settings
    admin = getattr(request.app.state, "litellm_admin", None) or LiteLLMAdmin(
        settings.litellm_base_url, settings.litellm_api_key
    )
    return ModelsAdminService(
        container.session_factory,
        admin,
        load_defaults(settings.litellm_models_path),
        container.model_catalog.invalidate,
        lockout=LockoutPolicy(settings.login_max_failures, settings.login_lockout_minutes),
        settings_service=container.settings_service,
    )


ServiceDep = Annotated[ModelsAdminService, Depends(get_service)]


@router.put("/{alias}", response_model=ModelChangeResult)
async def change_model(
    alias: Alias, body: ModelChangeIn, who: Writer, service: ServiceDep
) -> ModelChangeResult:
    """Сменить провайдера/модель/ключ роли в LiteLLM без перезапуска (re-auth, аудит без ключа)."""
    change = ModelChange(
        provider=body.provider,
        model=body.model.strip(),
        api_key=body.api_key.get_secret_value().strip() if body.api_key else None,
        api_base=body.api_base.strip() if body.api_base else None,
    )
    outcome = await service.change(who, alias, change, body.password.get_secret_value())
    return ModelChangeResult(**asdict(outcome))


@router.post("/{alias}/reset", response_model=ModelChangeResult)
async def reset_model(
    alias: Alias, body: ModelResetIn, who: Writer, service: ServiceDep
) -> ModelChangeResult:
    """Вернуть роль к значению по умолчанию (`infra/litellm.models.yaml`, ключ из env сервера)."""
    outcome = await service.reset(who, alias, body.password.get_secret_value())
    return ModelChangeResult(**asdict(outcome))


@router.put("/providers/{provider}/key", response_model=ProviderKeyResult)
async def change_provider_key(
    provider: Annotated[str, Path(max_length=32)],
    body: ProviderKeyIn,
    who: Writer,
    service: ServiceDep,
    container: ContainerDep,
) -> ProviderKeyResult:
    """Новый ключ провайдера для всех его ролей разом (W15-H3): один пароль, один аудит.

    Сначала создаются новые deployment всех ролей, потом удаляются прежние; сбой посередине
    откатывает созданное. После смены провайдер сразу проверяется (журнал шлюза, без платных
    вызовов моделей). Ключ уходит только в LiteLLM, в ответах и аудите — только последние 4 символа.
    """
    outcomes = await service.change_provider_key(
        who, provider, body.api_key.get_secret_value().strip(), body.password.get_secret_value()
    )
    checked = True
    try:
        await container.external_checks.run(
            "manual", datetime.now(UTC), keys=[f"vendor.{provider}"]
        )
    except Exception:  # noqa: BLE001 — ключ уже применён; проверка повторится по расписанию
        checked = False
    return ProviderKeyResult(
        provider=provider, roles=[ModelChangeResult(**asdict(o)) for o in outcomes], checked=checked
    )
