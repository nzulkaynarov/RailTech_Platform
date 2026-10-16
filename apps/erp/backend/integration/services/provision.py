"""User provisioning and session revocation service (ADR-0003, CONTRACTS §2, M3-ERP-01).

Источник истины по сотрудникам — CRM.
ERP провижинит пользователя, назначает роли бэк-офиса или права суперпользователя.
При снятии доступа в CRM — отзывает все сессии сотрудника в ERP.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from accounts.models import CompanyMember, CompanyRole, CustomUser
from core.tenant import own_company

from ..models import CrmUserMapping

logger = logging.getLogger(__name__)


@transaction.atomic
def provision_crm_user(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Провижининг сотрудника из CRM.

    Возвращает ({"erp_user_id": ..., "crm_user_id": ...}, created).
    """
    crm_user_id = data["crm_user_id"]
    email = data["email"].strip().lower()
    name = data["name"].strip()
    role = data["role"]  # 'admin' | 'backoffice'
    permissions = data.get("permissions") or []
    is_active = data.get("is_active", True)

    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    created = False

    if mapping:
        user = mapping.user
    else:
        user = CustomUser.objects.filter(email__iexact=email).first()
        if not user:
            user = CustomUser.objects.create(
                username=email,
                email=email,
                first_name=name,
                is_active=is_active,
            )
            created = True
        mapping = CrmUserMapping.objects.create(
            crm_user_id=crm_user_id,
            user=user,
        )

    # Обновление профиля пользователя
    user.email = email
    user.first_name = name
    user.is_active = is_active

    if role == "admin":
        user.is_superuser = True
        user.is_staff = True
    else:
        user.is_superuser = False
        user.is_staff = False

    user.save()

    # Привязка к компании бэк-офиса (own_company)
    company = own_company()
    if company:
        member, _ = CompanyMember.objects.get_or_create(
            user=user,
            company=company,
            defaults={"is_primary": True, "is_active": is_active},
        )
        if member.is_active != is_active:
            member.is_active = is_active
            member.save(update_fields=["is_active"])

        if role == "backoffice":
            role_name = f"CRM Sync: {user.email}"
            crm_role, _ = CompanyRole.objects.get_or_create(
                company=company,
                name=role_name,
                defaults={"permissions": permissions, "is_system": False, "created_by": user},
            )
            crm_role.permissions = permissions
            crm_role.save(update_fields=["permissions", "updated_at"])
            member.company_roles.set([crm_role])
        elif role == "admin":
            # Для админа роли бэк-офиса не требуются (is_superuser имеет все права)
            pass

    return {
        "erp_user_id": user.pk,
        "crm_user_id": crm_user_id,
    }, created


def revoke_crm_user_sessions(crm_user_id: int) -> bool:
    """Отзыв всех активных сессий сотрудника в ERP.

    Возвращает True если сотрудник найден и сессии отозваны, False если не найден.
    """
    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    if not mapping:
        return False

    user_id = mapping.user_id

    # 1. Завершение Django-сессий (Cookie)
    try:
        now = timezone.now()
        for s in Session.objects.filter(expire_date__gte=now):
            data = s.get_decoded()
            if str(data.get("_auth_user_id")) == str(user_id):
                s.delete()
    except Exception as exc:
        logger.warning("Error revoking django sessions for user %s: %s", user_id, exc)

    # 2. Блэклистинг токенов SimpleJWT (Bearer)
    try:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        for token in OutstandingToken.objects.filter(user_id=user_id):
            BlacklistedToken.objects.get_or_create(token=token)
    except Exception as exc:
        logger.warning("Error blacklisting jwt tokens for user %s: %s", user_id, exc)

    logger.info("Successfully revoked all sessions for CRM user %s (ERP user %s)", crm_user_id, user_id)
    return True
