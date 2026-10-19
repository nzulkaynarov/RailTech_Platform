"""User provisioning and session revocation service (ADR-0003, CONTRACTS §2, M3-ERP-01).

Источник истины по сотрудникам — CRM.
ERP провижинит пользователя, назначает роли бэк-офиса или права суперпользователя.
При снятии доступа в CRM — отзывает все сессии сотрудника в ERP.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from django.db import transaction
from django.db.models import F
from sales.models import ActivityLog

from accounts.models import CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.services.auth import revoke_user_refresh_tokens
from core.tenant import own_company

from ..exceptions import IntegrationConflict
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

    # Коллизия e-mail (I-17): адрес занят пользователем ERP, который не наш crm_user_id
    # (другое сопоставление или его нет) — не присваиваем и не переписываем чужого.
    holder = CustomUser.objects.filter(email__iexact=email).first()
    if holder is not None and (mapping is None or holder.pk != mapping.user_id):
        logger.warning("Provision refused: e-mail of crm_user %s is taken by ERP user %s", crm_user_id, holder.pk)
        raise IntegrationConflict("EMAIL_CONFLICT")

    if mapping:
        user = mapping.user
    else:
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

    # update_fields: полная запись затёрла бы `token_version`, выросший при параллельном отзыве доступа.
    user.save(update_fields=["email", "first_name", "is_active", "is_superuser", "is_staff"])

    # Привязка к компании бэк-офиса (own_company)
    company = own_company()
    if company:
        member, _ = CompanyMember.objects.get_or_create(
            user=user,
            company=company,
            # `role` (должность) обязательна; доступ определяют роли бэк-офиса ниже, не должность.
            defaults={
                "is_primary": True,
                "is_active": is_active,
                "role": WorkspaceRole.objects.get(code="MEMBER"),
            },
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


@transaction.atomic
def revoke_crm_user_sessions(crm_user_id: int) -> bool:
    """Снятие доступа к ERP по запросу CRM (`DELETE /users/{crm_user_id}/sessions`, sso-token.md «Отзыв»).

    Гасит всё, чем сотрудник входит: refresh-токены (чёрный список), уже выданные access-токены (версия
    токенов растёт — `accounts.authentication` отвечает 401) и сам вход (`is_active=False`: локальный пароль и
    его сброс доступа не возвращают). Повторный провижининг включает пользователя. Всё — запросами по
    одному пользователю: перебора чужих сессий нет (S-6). Идемпотентно; пишет `sso.revoke` в аудит.

    Возвращает True, если сотрудник найден; False — нет сопоставления с `crm_user_id`.
    """
    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    if not mapping:
        return False

    user_id = mapping.user_id
    CustomUser.objects.filter(pk=user_id).update(token_version=F("token_version") + 1, is_active=False)
    blacklisted = revoke_user_refresh_tokens(mapping.user)

    ActivityLog.objects.create(
        user=mapping.user,
        action="sso.revoke",
        event_code="sso.revoke",
        event_params={"crm_user_id": crm_user_id, "erp_user_id": user_id, "refresh_tokens": blacklisted},
        detail=f"Access revoked by CRM for crm_user #{crm_user_id} (ERP user #{user_id})",
    )
    logger.info("Revoked ERP access of CRM user %s (ERP user %s)", crm_user_id, user_id)
    return True
