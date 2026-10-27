"""Мост в старые экраны CRM и ERP, пока раздел Платформы ещё заглушка (tag `bridge`, 0.18.0).

BFF не решает, а подсказывает адрес: публичные адреса старых фронтов и вход в старый ERP тем же
путём, каким старая CRM открывает ERP (CRM `POST /auth/sso/token`, токен на 60 секунд,
`docs/architecture/sso-token.md`).
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response

from app.bridge_url import derive_public_url
from app.clients.crm_models import SsoTokenResponse
from app.config import Settings
from app.deps import Authed, SettingsDep, require_any_section
from app.errors import PlatformError, backend_reason, backend_unavailable, from_backend
from app.schemas_bridge import Bridge, BridgeErpSso

router = APIRouter(tags=["bridge"])
log = structlog.get_logger()

# Мост открыт любому вошедшему с разделами: права на сами экраны старых систем проверяют они.
BridgeAuthed = Annotated[Authed, Depends(require_any_section)]


def public_urls(request: Request, settings: Settings) -> tuple[str | None, str | None]:
    """(старая CRM, старый ERP): настройка, а пустая — вывод из адреса Платформы."""
    peer = request.client.host if request.client else None

    def pick(configured: str, sibling: str) -> str | None:
        return configured or derive_public_url(
            request.headers.get("host"),
            request.headers.get("x-forwarded-proto"),
            peer,
            settings.trusted_proxy_networks,
            sibling=sibling,
            request_scheme=request.url.scheme,
        )

    return pick(settings.crm_public_url, "crm"), pick(settings.erp_public_url, "erp")


@router.get("/bridge", response_model=Bridge, operation_id="getBridge")
async def get_bridge(
    request: Request, response: Response, settings: SettingsDep, authed: BridgeAuthed
) -> Bridge:
    crm_url, erp_url = public_urls(request, settings)
    response.headers["Cache-Control"] = "no-store"
    return Bridge(crm_url=crm_url, erp_url=erp_url, erp_sso="erp" in authed.data.platform_access)


@router.post("/bridge/erp-sso", response_model=BridgeErpSso, operation_id="createBridgeErpSso")
async def create_erp_sso(response: Response, authed: BridgeAuthed) -> BridgeErpSso:
    if "erp" not in authed.data.platform_access:
        raise PlatformError(
            "FORBIDDEN",
            "Доступ к ERP вам не выдан.",
            status_code=403,
            details={"reason": "platform_access_denied"},
        )
    resp = await authed.call("crm", "POST", "/api/v1/auth/sso/token")
    if resp.status_code == 403:
        # CRM отказала: нет доступа к ERP или переход по SSO выключен (`PLATFORM_SSO_ENABLED`).
        raise PlatformError(
            "FORBIDDEN",
            "Вход в старый ERP без второго пароля недоступен.",
            status_code=403,
            source="crm",
            details={"reason": backend_reason(resp) or "sso_disabled"},
        )
    if resp.status_code != 200:
        raise from_backend("crm", resp)
    try:
        sso = SsoTokenResponse.model_validate(resp.json())
    except ValueError as exc:
        log.warning("bridge_sso_bad_body")
        raise backend_unavailable("crm", "sso_failed") from exc
    response.headers["Cache-Control"] = "no-store"
    return BridgeErpSso(url=f"{sso.redirect_url}#token={sso.token}")
