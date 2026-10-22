"""User provisioning and session revocation service (ADR-0003, CONTRACTS §2, M3-ERP-01).

Источник истины по сотрудникам — CRM.
ERP провижинит пользователя, назначает роли бэк-офиса или права суперпользователя.
При снятии доступа в CRM — отзывает все сессии сотрудника в ERP.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from django.db import transaction
from django.db.models import F
from sales.models import ActivityLog

from accounts.models import CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.services.auth import revoke_user_refresh_tokens
from accounts.services.roles import SYNC_ROLE_PREFIX, ensure_default_company_roles
from core.audit import log_admin_action
from core.tenant import own_company

from ..exceptions import IntegrationConflict
from ..models import CrmUserMapping

logger = logging.getLogger(__name__)


def sync_role_name(email: str) -> str:
    """Имя управляемой роли сотрудника, провижиненного из CRM."""
    return f"{SYNC_ROLE_PREFIX}{email}"


def split_full_name(name: str) -> Tuple[str, str]:
    """«Иван Петров» → («Иван», «Петров»): имя — первое слово, фамилия — остаток; одно слово — только имя."""
    first, _, last = name.strip().partition(" ")
    return first[:150], last.strip()[:150]


def _drop_crm_roles(member: CompanyMember) -> None:
    """Снять с участника роли, которые ведёт CRM: «CRM Sync: <e-mail>» и системные, выданные по `role_codes`.
    Ручные роли не трогаются."""
    granted = list(member.crm_granted_roles.all())
    member.company_roles.remove(*member.company_roles.filter(managed_by_crm=True), *granted)
    member.crm_granted_roles.clear()


def _sync_system_roles(member: CompanyMember, role_codes, company) -> None:
    """Системные роли из CRM (`role_codes`, FIX-63, Q-FIX50-1 (1)).

    Добавляет пришедшие и помечает их «выдана из CRM» (`crm_granted_roles`); снимает только помеченные, которых в
    `role_codes` больше нет. Роль, уже назначенная в ERP вручную, не помечается — CRM её не отнимет. Пометка, чья
    роль снята в «Команде» вручную, пропадает; если CRM всё ещё выдаёт её, роль вернётся и пометится заново."""
    system_roles = ensure_default_company_roles(company)
    wanted_ids = {system_roles[code].pk for code in set(role_codes)}
    current = set(member.company_roles.values_list("pk", flat=True))
    granted = set(member.crm_granted_roles.values_list("pk", flat=True)) & current
    member.company_roles.remove(*(granted - wanted_ids))
    granted &= wanted_ids
    new_ids = wanted_ids - current
    if new_ids:
        member.company_roles.add(*new_ids)
        granted |= new_ids
    member.crm_granted_roles.set(granted)


def bind_member_to_company(
    user: CustomUser,
    company,
    *,
    role: str,
    permissions,
    role_codes,
    is_active: bool,
) -> CompanyMember:
    """Участник своей компании с ролями из провижининга CRM (идемпотентно: get_or_create, роли — add/remove)."""
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
        # Провижининг управляет только СВОЕЙ ролью «CRM Sync: <e-mail>»: создаёт, обновляет права и
        # добавляет (add), а роли, выданные в ERP вручную, не трогает (FIX-55, D-07; Q-FIX50-1 (2)).
        crm_role, _ = CompanyRole.objects.get_or_create(
            company=company,
            name=sync_role_name(user.email),
            defaults={"permissions": permissions, "is_system": False, "created_by": user},
        )
        crm_role.permissions = permissions
        crm_role.managed_by_crm = True
        crm_role.save(update_fields=["permissions", "managed_by_crm", "updated_at"])
        member.company_roles.add(crm_role)
        # Сменился e-mail сотрудника — прежняя «CRM Sync: <старый e-mail>» больше не его: снимаем остальные
        # управляемые роли, ручные не трогаем.
        member.company_roles.remove(*member.company_roles.filter(managed_by_crm=True).exclude(pk=crm_role.pk))
        if role_codes is not None:
            _sync_system_roles(member, role_codes, company)
    else:
        # Админу роли бэк-офиса не нужны (is_superuser имеет все права): снимаем только роли из CRM
        # (свою «CRM Sync» и выданные по `role_codes`), если сотрудник был backoffice; ручные роли остаются.
        if role_codes is not None:
            _drop_crm_roles(member)
        else:
            member.company_roles.remove(*member.company_roles.filter(managed_by_crm=True))
    return member


@transaction.atomic
def attach_provisioned_users(company, actor=None) -> List[int]:
    """Привязать к только что созданной своей компании сотрудников, которых CRM провижинила ДО неё (FIX-P1-2, QA-P1-D-2).

    Пока своей компании нет, `provision_crm_user` сохраняет пользователя и сопоставление, но члена компании
    создавать некуда. Здесь — те же шаги, что у провижининга (`bind_member_to_company`), по сохранённому
    `CrmUserMapping.provision_snapshot`: роль, права, `role_codes`. Берутся только активные пользователи (отключённый
    в CRM или отозванный — `is_active=False` — не привязывается: вернётся следующим провижинингом). Идемпотентно:
    уже участник — роли выравниваются, дублей нет. Сопоставление без снимка (создано до поля) получает роль по
    `is_superuser` и минимальные права: ни `permissions`, ни системных ролей.

    Возвращает ERP-id привязанных пользователей; в аудит пишет одну запись (если кого-то привязали).
    """
    attached: List[int] = []
    mappings = CrmUserMapping.objects.filter(user__is_active=True).select_related("user").order_by("pk")
    for mapping in mappings:
        user = mapping.user
        snapshot = mapping.provision_snapshot or {}
        role = snapshot.get("role") or ("admin" if user.is_superuser else "backoffice")
        bind_member_to_company(
            user,
            company,
            role=role,
            permissions=snapshot.get("permissions") or [],
            role_codes=snapshot.get("role_codes"),
            is_active=True,
        )
        attached.append(user.pk)

    if attached:
        log_admin_action(
            entity_type="company",
            entity_id=company.id,
            action="Сотрудники из CRM привязаны к своей компании",
            detail=f"{company.name}: привязано сотрудников, заведённых из CRM до создания компании — {len(attached)}",
            # Без `event_code`: подпись берётся из `action` (русский текст). Структурный код требует словаря
            # во фронтенде ERP (тест activityCoverage), а он заморожен.
            after={"count": len(attached), "erp_user_ids": attached},
            actor=actor,
            company_id=company.id,
        )
        logger.info("Attached %s CRM-provisioned users to own company %s", len(attached), company.pk)
    return attached


@transaction.atomic
def provision_crm_user(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Провижининг сотрудника из CRM.

    Возвращает ({"erp_user_id": ..., "crm_user_id": ...}, created).
    """
    crm_user_id = data["crm_user_id"]
    email = data["email"].strip().lower()
    name = data["name"].strip()
    first_name, last_name = split_full_name(name)
    role = data["role"]  # 'admin' | 'backoffice'
    permissions = data.get("permissions") or []
    is_active = data.get("is_active", True)
    # None — поля нет (старый CRM): системные роли не трогаем; [] — снять все, выданные из CRM.
    role_codes = data.get("role_codes")

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
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )
        created = True
        mapping = CrmUserMapping.objects.create(
            crm_user_id=crm_user_id,
            user=user,
        )

    # Обновление профиля пользователя
    # Имя приходит из CRM одной строкой. Профиль в ERP принадлежит сотруднику: имя и фамилию правят там вручную,
    # поэтому при повторной синхронизации заполняем их только если обе части пусты (FIX-55, D-12).
    update_fields = ["email", "is_active", "is_superuser", "is_staff"]
    if not (user.first_name or user.last_name):
        user.first_name, user.last_name = first_name, last_name
        update_fields += ["first_name", "last_name"]
    user.email = email
    user.is_active = is_active

    if role == "admin":
        user.is_superuser = True
        user.is_staff = True
    else:
        user.is_superuser = False
        user.is_staff = False

    # update_fields: полная запись затёрла бы `token_version`, выросший при параллельном отзыве доступа.
    user.save(update_fields=update_fields)

    # Что пришло в последний раз — для привязки к своей компании, созданной позже (FIX-P1-2).
    mapping.provision_snapshot = {"role": role, "permissions": list(permissions), "role_codes": role_codes}
    mapping.save(update_fields=["provision_snapshot", "updated_at"])

    # Привязка к компании бэк-офиса (own_company)
    company = own_company()
    if company:
        bind_member_to_company(
            user, company, role=role, permissions=permissions, role_codes=role_codes, is_active=is_active
        )

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
    # Роли из CRM уходят вместе с доступом — «CRM Sync» и системные, выданные по `role_codes`; ручные роли остаются
    # (вернётся доступ — вернётся и роль, FIX-55, D-07; FIX-63).
    for member in CompanyMember.objects.filter(user_id=user_id):
        _drop_crm_roles(member)
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
