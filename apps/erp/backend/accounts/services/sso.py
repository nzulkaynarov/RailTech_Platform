"""SSO Token Service (CRM ↔ ERP, CONTRACTS §6, packages/contracts/sso-token.md, M3-CRM-06).

Реализует:
1. Выпуск SSO-токена JWT HS256 для перехода в CRM (iss=erp, aud=crm).
2. Проверку и обмен входящего SSO-токена (iss=crm, aud=erp).
3. Проверку срока (60 с), допуск часов (≤ 5 с), одноразовость jti (10 мин в кэше).
4. Провижининг/обновление пользователя и запись в аудит (ActivityLog).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import jwt
from django.conf import settings
from django.core.cache import cache
from integration.models import CrmUserMapping
from integration.services.provision import provision_crm_user
from sales.models import ActivityLog

from accounts.constants import Permission
from accounts.models import CompanyMember, CustomUser
from core.tenant import own_company

logger = logging.getLogger(__name__)

SSO_ALGORITHM = "HS256"
SSO_TOKEN_TTL_S = 60
SSO_CLOCK_LEEWAY_S = 5
SSO_JTI_CACHE_TTL_S = 600  # 10 минут


class SsoError(Exception):
    """Базовая ошибка SSO."""

    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class SsoValidationError(SsoError):
    def __init__(self, detail: str = "INVALID_SSO_TOKEN"):
        super().__init__(detail=detail, status_code=401)


class SsoForbiddenError(SsoError):
    def __init__(self, detail: str = "FORBIDDEN"):
        super().__init__(detail=detail, status_code=403)


def get_sso_secrets() -> List[str]:
    raw = getattr(settings, "PLATFORM_SSO_SECRET", ["dev-platform-sso-secret"])
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(s).strip() for s in raw if str(s).strip()]
    return ["dev-platform-sso-secret"]


def build_staff_user_payload(user: CustomUser, crm_user_id: Optional[int] = None) -> Dict[str, Any]:
    if crm_user_id is None:
        mapping = CrmUserMapping.objects.filter(user=user).first()
        crm_user_id = mapping.crm_user_id if mapping else user.pk

    company = own_company()
    member = CompanyMember.objects.filter(user=user, company=company, is_active=True).first() if company else None

    roles: List[Dict[str, str]] = []
    permissions: List[str] = []

    if user.is_superuser:
        roles.append({"code": "admin", "name": "Администратор"})
        permissions = [p.value for p in Permission]
    elif member:
        for r in member.company_roles.all():
            code = (r.code or "calculation").lower()
            roles.append({"code": code, "name": r.name})
            if isinstance(r.permissions, list):
                for p in r.permissions:
                    if p not in permissions:
                        permissions.append(p)
    if not roles:
        roles.append({"code": "calculation", "name": "Расчёт"})

    return {
        "erp_user_id": user.pk,
        "crm_user_id": crm_user_id,
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "roles": roles,
        "permissions": permissions,
        "platform_access": ["crm", "erp"],
    }


def issue_sso_token(user: CustomUser) -> Tuple[str, str]:
    if not user.is_active:
        raise SsoForbiddenError("USER_INACTIVE")

    secrets = get_sso_secrets()
    secret = secrets[0] if secrets else "dev-platform-sso-secret"

    mapping = CrmUserMapping.objects.filter(user=user).first()
    crm_user_id = mapping.crm_user_id if mapping else user.pk

    now = int(time.time())
    jti = str(uuid.uuid4())

    payload = {
        "iss": "erp",
        "aud": "crm",
        "sub": str(crm_user_id),
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "role": "admin" if user.is_superuser else "manager",
        "permissions": [],
        "iat": now,
        "exp": now + SSO_TOKEN_TTL_S,
        "jti": jti,
    }

    token = jwt.encode(payload, secret, algorithm=SSO_ALGORITHM)
    crm_base = getattr(settings, "CRM_FRONTEND_URL", "http://crm.localhost").rstrip("/")
    redirect_url = f"{crm_base}/sso/exchange"

    return token, redirect_url


def verify_and_exchange_sso_token(token: str, client_ip: Optional[str] = None) -> Tuple[CustomUser, Dict[str, Any]]:
    if not token or not isinstance(token, str):
        raise SsoValidationError("TOKEN_REQUIRED")

    secrets = get_sso_secrets()
    payload = None
    last_err = None

    for secret in secrets:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[SSO_ALGORITHM],
                audience="erp",
                issuer="crm",
                leeway=SSO_CLOCK_LEEWAY_S,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
            )
            break
        except (jwt.ExpiredSignatureError, jwt.InvalidAudienceError, jwt.InvalidIssuerError) as e:
            last_err = e
            break  # Нарушение claims — повторная проверка другим секретом не поможет
        except jwt.PyJWTError as e:
            last_err = e
            continue

    if payload is None:
        logger.warning("SSO token verification failed: %s", last_err)
        raise SsoValidationError("INVALID_SSO_TOKEN")

    jti = payload.get("jti")
    if not jti:
        raise SsoValidationError("INVALID_JTI")

    # 4. Проверка одноразовости jti (хранится 10 минут)
    cache_key = f"sso_jti:{jti}"
    was_added = cache.add(cache_key, True, timeout=SSO_JTI_CACHE_TTL_S)
    if not was_added:
        logger.warning("SSO token replay attack detected: jti=%s", jti)
        raise SsoValidationError("TOKEN_ALREADY_USED")

    # 5. Поиск и провижининг пользователя по sub (crm_user_id)
    try:
        crm_user_id = int(payload["sub"])
    except (ValueError, TypeError):
        raise SsoValidationError("INVALID_SUB")

    email = str(payload.get("email") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    role_raw = payload.get("role", "manager")
    erp_role = "admin" if role_raw == "admin" else "backoffice"
    permissions = payload.get("permissions") or []

    # Проверяем, существует ли пользователь и не деактивирован ли он
    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    if mapping and not mapping.user.is_active:
        raise SsoForbiddenError("USER_INACTIVE")

    if not mapping and email:
        existing_by_email = CustomUser.objects.filter(email__iexact=email).first()
        if existing_by_email and not existing_by_email.is_active:
            raise SsoForbiddenError("USER_INACTIVE")

    prov_res, _ = provision_crm_user(
        {
            "crm_user_id": crm_user_id,
            "email": email,
            "name": name,
            "role": erp_role,
            "permissions": permissions,
            "is_active": True,
        }
    )
    user = CustomUser.objects.filter(pk=prov_res["erp_user_id"]).first()
    if not user or not user.is_active:
        raise SsoForbiddenError("USER_INACTIVE")

    # 6. Аудит sso.exchange
    try:
        ActivityLog.objects.create(
            user=user,
            action="sso.exchange",
            event_code="sso.exchange",
            event_params={
                "iss": payload.get("iss"),
                "sub": payload.get("sub"),
                "jti": jti,
                "ip": client_ip or "",
            },
            detail=f"SSO exchange from {payload.get('iss')} for crm_user #{crm_user_id} (jti={jti})",
        )
    except Exception as e:
        logger.warning("Failed to record ActivityLog for sso.exchange: %s", e)

    staff_user = build_staff_user_payload(user, crm_user_id=crm_user_id)
    return user, staff_user
