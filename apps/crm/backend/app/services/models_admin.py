"""Смена провайдера, модели и ключа роли из CRM (ADR-0020) — обёртка над API моделей LiteLLM.

Ключ провайдера уходит только в LiteLLM (шифруется там `LITELLM_SALT_KEY`); в нашу БД, аудит и
логи попадают лишь последние 4 символа. Замена = создать новую deployment алиаса, затем удалить
старые: запись с тем же алиасом в LiteLLM — вторая deployment группы, не замена (проверено).
"""

import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.litellm import EMBED_ALIAS
from app.integrations.litellm_admin import (
    DefaultModel,
    Deployment,
    LiteLLMAdmin,
    LiteLLMAdminError,
    env_keys,
)
from app.repositories import users as users_repo
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import last4
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

PROVIDERS: Final = ("anthropic", "gemini", "openai")
DIALOG_ALIAS: Final = "dialog-model"
# Параметры роли, не зависящие от провайдера: переносятся из значений по умолчанию.
CARRY_PARAMS: Final = ("timeout", "stream_timeout", "reasoning_effort")
_MODEL_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_BASE_RE: Final = re.compile(r"^https?://[^\s]{1,250}$")


@dataclass(frozen=True, slots=True)
class ModelChange:
    provider: str
    model: str
    api_key: str | None = None
    api_base: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeOutcome:
    alias: str
    provider: str
    model: str
    key_source: str  # "crm" | "env"
    reindex_required: bool
    quality_check_recommended: bool


def validate(change: ModelChange) -> None:
    if change.provider not in PROVIDERS:
        raise ValidationFailedError("unknown provider", field="provider")
    if not _MODEL_RE.match(change.model) or change.model.startswith(f"{change.provider}/"):
        raise ValidationFailedError("model id is invalid", field="model")
    if change.api_base is not None and not _BASE_RE.match(change.api_base):
        raise ValidationFailedError("api base is invalid", field="api_base")
    if change.api_key is not None and not 8 <= len(change.api_key) <= 512:
        raise ValidationFailedError("api key is invalid", field="api_key")


def build_params(
    alias: str, change: ModelChange, defaults: Mapping[str, DefaultModel]
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Параметры новой deployment: модель, ключ (введённый или `os.environ/…`), общие параметры.

    `model_info` берётся из значения по умолчанию с той же моделью (флаги вроде
    `supports_adaptive_thinking`, цены), иначе пуст — тогда действует карта моделей LiteLLM.
    """
    full_model = f"{change.provider}/{change.model}"
    base = defaults[alias].litellm_params
    params: dict[str, Any] = {k: base[k] for k in CARRY_PARAMS if k in base}
    params["model"] = full_model
    if change.api_key:
        params["api_key"], source = change.api_key, "crm"
    else:
        ref = env_keys(defaults).get(change.provider)
        if ref is None:
            raise ValidationFailedError(
                "api key is required", reason=Reason.MODEL_KEY_REQUIRED, field="api_key"
            )
        params["api_key"], source = ref, "env"
    if change.api_base:
        params["api_base"] = change.api_base
    info = next((dict(d.model_info) for d in defaults.values() if d.model == full_model), {})
    return params, info, source


def _split(model: str) -> tuple[str, str]:
    provider, _, name = model.partition("/")
    return provider, name


class ModelsAdminService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        admin: LiteLLMAdmin,
        defaults: Mapping[str, DefaultModel],
        invalidate: Callable[[], None],
        lockout: reauth.LockoutPolicy | None = None,
        new_id: Callable[[str], str] | None = None,
        settings_service: SettingsService | None = None,
    ) -> None:
        self._sessions = sessions
        self._admin = admin
        self._defaults = defaults
        self._invalidate = invalidate
        self._lockout = lockout or reauth.LockoutPolicy()
        self._new_id = new_id or (lambda alias: f"rt-{alias}-{secrets.token_hex(4)}")
        self._settings = settings_service

    async def change(
        self, who: Principal, alias: str, change: ModelChange, password: str
    ) -> ChangeOutcome:
        self._known(alias)
        validate(change)
        await self._reauth(who.user_id, password)
        params, info, source = build_params(alias, change, self._defaults)
        return await self._replace(who, alias, params, info, source, "model.update")

    async def reset(self, who: Principal, alias: str, password: str) -> ChangeOutcome:
        default = self._known(alias)
        await self._reauth(who.user_id, password)
        return await self._replace(
            who, alias, dict(default.litellm_params), dict(default.model_info), "env", "model.reset"
        )

    async def seed(self) -> list[str]:
        """Создать в БД LiteLLM отсутствующие алиасы из значений по умолчанию (идемпотентно)."""
        present = {d.alias for d in await self._admin_call(self._admin.deployments)}
        created: list[str] = []
        for alias, default in self._defaults.items():
            if alias in present:
                continue
            await self._admin_call(
                partial(
                    self._admin.create,
                    self._new_id(alias),
                    alias,
                    default.litellm_params,
                    default.model_info,
                )
            )
            created.append(alias)
        logger.info("litellm_seed_done", created=created)
        return created

    def _known(self, alias: str) -> DefaultModel:
        default = self._defaults.get(alias)
        if default is None:
            raise NotFoundError("unknown model alias")
        return default

    async def _replace(
        self,
        who: Principal,
        alias: str,
        params: dict[str, Any],
        info: dict[str, Any],
        source: str,
        action: str,
    ) -> ChangeOutcome:
        key = params.get("api_key")
        old = [d for d in await self._admin_call(self._admin.deployments) if d.alias == alias]
        if any(not d.in_db for d in old):
            raise ConflictError("alias is defined in litellm config", reason=Reason.MODEL_IN_CONFIG)
        await self._admin_call(
            lambda: self._admin.create(self._new_id(alias), alias, params, info), secret=key
        )
        for dep in old:
            await self._admin_call(partial(self._admin.delete, dep.id))
        self._invalidate()
        provider, model = _split(str(params["model"]))
        await self._audit(who, alias, old, params, source, action)
        await self._remember_key(who, alias, source, key)
        logger.info("model_changed", alias=alias, provider=provider, model=model, key=source)
        old_models = {d.model for d in old}
        return ChangeOutcome(
            alias=alias,
            provider=provider,
            model=model,
            key_source=source,
            reindex_required=alias == EMBED_ALIAS and old_models != {params["model"]},
            quality_check_recommended=alias == DIALOG_ALIAS,
        )

    async def _remember_key(self, who: Principal, alias: str, source: str, key: object) -> None:
        """Маска ключа для экрана: источник и последние 4 символа; сам ключ нигде не хранится."""
        if self._settings is None:
            return
        current = (await self._settings.get()).integrations.model_dump(mode="json")
        masks = dict(current.get("model_keys") or {})
        masks[alias] = {
            "source": source,
            "last4": last4(str(key)) if source == "crm" and key else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        current["model_keys"] = masks
        await self._settings.update("integrations", current, who.user_id)

    async def _audit(
        self,
        who: Principal,
        alias: str,
        old: list[Deployment],
        params: Mapping[str, Any],
        source: str,
        action: str,
    ) -> None:
        key = str(params.get("api_key") or "")
        after = {
            "model": params["model"],
            "api_base": params.get("api_base"),
            "key": f"…{last4(key)}" if source == "crm" else "env",
        }
        async with self._sessions() as session, session.begin():
            await audit.record(
                session,
                who.actor,
                action,
                "model",
                alias,
                before={"models": sorted(d.model or "" for d in old)},
                after=after,
            )

    async def _admin_call[T](self, call: Callable[[], Awaitable[T]], secret: object = None) -> T:
        try:
            return await call()
        except LiteLLMAdminError as exc:
            detail = exc.detail
            if isinstance(secret, str) and secret and not secret.startswith("os.environ/"):
                detail = detail.replace(secret, "***")
            raise UpstreamUnavailableError(
                "litellm rejected the change", reason=Reason.LITELLM_UNAVAILABLE, detail=detail
            ) from exc

    async def _reauth(self, user_id: int, password: str) -> None:
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure
