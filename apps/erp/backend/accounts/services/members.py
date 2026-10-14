import logging
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Q
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.audit import log_admin_action
from notifications.emails import send_templated_email

from ..constants import WorkspaceRoleCode
from ..models import Company, CompanyMember, CustomUser, SystemRole, WorkspaceRole

logger = logging.getLogger(__name__)


def invite_workspace_member(company: Company, email: str, role_code: str) -> Tuple[Optional[CustomUser], Optional[str]]:
    if not email:
        return None, "EMAIL_REQUIRED"

    if CustomUser.objects.filter(email=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    w_role = WorkspaceRole.objects.filter(code=role_code).first()
    if not w_role:
        return None, "SYSTEM_ROLE_NOT_FOUND"

    # Default system role for invited member: USER (пользователь компании).
    user_role = SystemRole.objects.filter(code="USER").first()

    user = CustomUser.objects.create(
        username=email,
        email=email,
        is_active=False,
        role=user_role,
    )
    user.set_unusable_password()
    user.save()

    member = CompanyMember.objects.create(user=user, company=company, role=w_role, is_primary=True)
    # Give the invited member a starting CompanyRole mapped from their WorkspaceRole, so the G4
    # access matrix governs them from day one (not the can_sell/can_buy fallback). The company
    # admin can re-assign later in «Команда и доступы».
    from .roles import default_company_role_for

    member.company_role = default_company_role_for(company, role_code)
    member.save(update_fields=["company_role"])

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.FRONTEND_URL
    setup_url = f"{base_url}/setup-password?uid={uid}&token={token}"

    send_templated_email(
        "invite_member",
        {"company_name": company.name, "setup_url": setup_url},
        to=[email],
        channel="transactional",
        user=user,
        fail_silently=True,
    )
    return user, None


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


def create_platform_user(
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    position: str = "",
    role_code: str = "",
    actor: Optional[CustomUser] = None,
    reason: str = "",
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """Завести пользователя из операторской панели и позвать его установить пароль.

    Путь был мёртв: форма «Новый пользователь» отдавала 400 `username` (поле обязательное у
    `AbstractUser`, а операторская форма его не спрашивает — и правильно, вход по email), а
    выбор системной роли не действовал вовсе (`role` лежит в `read_only_fields`
    `UserSerializer`). Даже если бы запрос прошёл, аккаунт родился бы с непригодным паролем и
    без единой возможности войти.

    Эталоны одинаковы: Salesforce «New User» и Odoo «Invite user» создают неактивную запись и
    шлют письмо со ссылкой на установку пароля — оператор НЕ придумывает и не передаёт пароль.
    Делаем так же: `is_active=False`, `set_unusable_password()`, письмо со ссылкой
    `/setup-password`, активация — в момент, когда человек задал пароль
    (`verify_and_setup_password`).

    Роль применяется через `change_user_role`, чтобы инварианты платформы (ADMIN только без
    членств) действовали и здесь, а не только на экране смены роли.
    """
    email = (email or "").strip().lower()
    if not email:
        return None, "EMAIL_REQUIRED"
    if CustomUser.objects.filter(email__iexact=email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    default_role = SystemRole.objects.filter(code="USER").first()
    user = CustomUser.objects.create(
        # `username` заполняем сами: колонка обязательна (`AbstractUser`), но входа по ней нет
        # (`USERNAME_FIELD = "email"`), поэтому спрашивать её у оператора незачем. Тот же приём
        # уже используется при импорте XLSX (`UserResource.before_import_row`).
        username=email,
        email=email,
        first_name=first_name or "",
        last_name=last_name or "",
        phone=phone or "",
        position=position or "",
        is_active=False,
        role=default_role,
    )
    user.set_unusable_password()
    user.save()

    if role_code and default_role is not None and role_code != default_role.code:
        _updated, role_error = change_user_role(user, role_code, actor=actor, reason=reason)
        if role_error:
            # Роль не прошла инварианты — аккаунт не создаём вовсе, иначе оператор получит
            # пользователя не с той ролью и молчаливое расхождение с тем, что он выбрал.
            user.delete()
            return None, role_error

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    setup_url = f"{settings.FRONTEND_URL}/setup-password?uid={uid}&token={token}"
    send_templated_email(
        "account_created_by_operator",
        {"first_name": user.first_name, "setup_url": setup_url},
        to=[user.email],
        channel="transactional",
        user=user,
        fail_silently=True,
    )
    log_admin_action(
        entity_type="user",
        entity_id=user.pk,
        action="Пользователь заведён оператором",
        detail=user.email,
        actor=actor,
        reason=reason,
        event_code="admin.user.created",
        event_params={"email": user.email},
        after={"email": user.email, "role": user.role.code if user.role_id else ""},
        level="SUCCESS",
    )
    return user, None


def can_delete_user(user: CustomUser) -> Optional[str]:
    """Почему этого пользователя нельзя удалить насовсем (или None, если можно).

    Жёсткое удаление в операторской панели работало мимо всех инвариантов:

    * `CompanyMember.user` каскадный — удаление последнего администратора компании оставляло
      её без единого ответственного, хотя ровно это запрещает never-orphan
      (`remove_company_member` → `CANNOT_REMOVE_LAST_COMPANY_ADMIN`);
    * таблицы истории pghistory ссылаются на пользователя с `DO_NOTHING` и живым FK в БД, так
      что удаление любого, кто хоть раз действовал по сделке, падало `IntegrityError` → 500.

    Эталоны здесь единодушны: Salesforce пользователя удалить нельзя в принципе, только
    деактивировать; Odoo архивирует (`active=False`). Поэтому запрет — не «новая блокировка»,
    а приведение к тому, что и так заявлено кнопкой «Деактивировать».
    """
    if user.is_superuser:
        return "CANNOT_DELETE_SUPERUSER"

    for membership in user.memberships.filter(is_active=True).select_related("company"):
        is_admin = company_active_admins(membership.company).filter(pk=membership.pk).exists()
        if is_admin and not company_active_admins(membership.company).exclude(pk=membership.pk).exists():
            return "CANNOT_REMOVE_LAST_COMPANY_ADMIN"

    from crm.models import Deal, Quote

    has_history = (
        Deal.objects.filter(Q(client=user) | Q(manager=user) | Q(assigned_to=user)).exists()
        or Quote.objects.filter(Q(prepared_by=user) | Q(approved_by=user)).exists()
    )
    if has_history:
        return "USER_HAS_HISTORY_DEACTIVATE_INSTEAD"
    return None


def change_user_role(
    user: CustomUser,
    role_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = "",
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Change SystemRole of a user.

    Инварианты платформы:
      - ADMIN выдаётся только пользователям без активных memberships
        (Platform Admin — владелец платформы, не привязан ни к одной компании).
      - Понизить ADMIN → USER разрешено всегда.
      - USER можно выдать любому юзеру.

    `actor` — кто меняет. Выдача роли ADMIN делает человека оператором платформы: он
    начинает видеть чужие компании и деньги. До 20-08 это не оставляло следа —
    в журнале доступа не было ни строки о том, кто и когда выдал платформенные права.
    """
    if not role_code:
        return None, "ROLE_CODE_REQUIRED"
    role = SystemRole.objects.filter(code=role_code).first()
    if not role:
        return None, "SYSTEM_ROLE_NOT_FOUND"
    if role.code == "ADMIN":
        has_active_memberships = user.memberships.filter(is_active=True).exists()
        if has_active_memberships:
            return None, "ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS"
    before_code = user.role.code if user.role_id else ""
    user.role = role
    user.save(update_fields=["role"])
    log_admin_action(
        entity_type="user",
        entity_id=user.pk,
        action="Системная роль изменена",
        detail=f"{user.email}: {before_code or '—'} → {role.code}",
        actor=actor,
        reason=reason,
        # `admin.*` — машинный признак «административное действие над чужими правами». По нему
        # событие попадает в операторский «Журнал доступа» и локализуется на языке смотрящего
        # (до этого лента печатала русскую строку `action` и англоязычному оператору).
        event_code="admin.user.role_changed",
        event_params={"email": user.email, "before": before_code or "", "after": role.code},
        before={"role": before_code},
        after={"role": role.code},
        # Выдача ADMIN = выдача доступа ко всей платформе, это не рядовая правка профиля.
        level="WARNING" if role.code == "ADMIN" else "INFO",
    )
    return user, None


def add_company_member(
    user: CustomUser,
    company: Company,
    workspace_role_code: str,
    is_primary: bool = False,
) -> Tuple[Optional["CompanyMember"], Optional[str]]:
    """
    Add or update a CompanyMember link between user and company.

    Инварианты платформы:
      - Platform Admin (role=ADMIN) не может быть членом компании.
      - workspace_role должен быть применим к типам компании (applicable_to_types).
    """
    if user.role and user.role.code == "ADMIN":
        return None, "PLATFORM_ADMIN_CANNOT_JOIN_COMPANY"
    role = WorkspaceRole.objects.filter(code=workspace_role_code).first()
    if not role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"
    applicable = role.applicable_to_types.all()
    if applicable.exists():
        company_type_codes = set(company.types.values_list("code", flat=True))
        allowed_codes = set(applicable.values_list("code", flat=True))
        if not (company_type_codes & allowed_codes):
            return None, "WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE"
    # Основное членство у человека РОВНО ОДНО — это ограничение БД
    # (`unique_primary_company_per_user`, миграция accounts/0007). Прежде сервис просто ставил
    # флаг, и добавление второй компании с галкой «Сделать основным» било `IntegrityError`
    # наружу: оператор видел 500 вместо результата, а членство не создавалось вовсе.
    #
    # Правильное поведение — ПЕРЕНАЗНАЧЕНИЕ, а не отказ: человек работает в нескольких
    # компаниях, и смена основной — обычная операция (эталон Odoo: переключение компании у
    # пользователя, а не запрет второй). Снимаем признак с прежней основной в той же
    # транзакции, что и ставим новый, — иначе между двумя записями существует момент, когда
    # основных два, и ограничение сработает на первой же параллельной попытке.
    with transaction.atomic():
        if is_primary:
            CompanyMember.objects.filter(user=user, is_primary=True).exclude(company=company).update(is_primary=False)
        membership, _created = CompanyMember.objects.update_or_create(
            user=user,
            company=company,
            defaults={"role": role, "is_primary": is_primary, "is_active": True},
        )
    # Seed the permission-engine CompanyRole exactly like invite_workspace_member
    # does, so this operator path stops minting permission-less
    # company_role=NULL members (which the G4 permission engine can only serve via the
    # shrinking legacy fallback). Only when missing — never clobber an admin's custom
    # role assignment on a re-add.
    if membership.company_role_id is None:
        from .roles import default_company_role_for

        membership.company_role = default_company_role_for(company, workspace_role_code)
        membership.save(update_fields=["company_role"])
    return membership, None


def _admin_floor_q() -> "Q":
    """The never-orphan admin floor as ONE reusable predicate (ADR-0005 Phase E U3).

    A member counts as a company admin if they hold the immutable is_system
    «Администратор компании» CompanyRole — the SAME floor `roles.py` enforces on
    CompanyRole reassignment — OR, during the WorkspaceRole→CompanyRole transition,
    they are an un-migrated legacy OWNER (company_role IS NULL). The legacy clause is
    what keeps never-orphan protecting tenants whose members predate the 0030 backfill:
    without it, deleting/deactivating the sole legacy OWNER (whose admin rights come
    from member_has_permission's OWNER fallback) would silently orphan the company.
    Unifying every never-orphan check on this predicate removes the two-definitions
    divergence window the deprecation ADR called out.
    """
    return Q(company_role__is_system=True) | Q(company_role__isnull=True, role__code=WorkspaceRoleCode.OWNER)


def company_active_admins(company: Company):
    """The company's irreducible admin set for the never-orphan invariant.

    See `_admin_floor_q` for the unified definition. Used by remove_company_member,
    set_member_workspace_role and toggle_user_active — all share this one query.
    """
    return CompanyMember.objects.filter(_admin_floor_q(), company=company, is_active=True)


def remove_company_member(
    membership: "CompanyMember",
) -> Tuple[Optional[bool], Optional[str]]:
    """
    Remove a member, enforcing the never-orphan invariant.

    A company must ALWAYS keep at least one active admin — the party accountable
    for billing. Removing the last one would orphan the company, so it's
    refused; the admin role must be transferred first. "Admin" is the unified
    is_system / legacy-OWNER floor (see `_admin_floor_q`).
    """
    is_admin = membership.is_active and company_active_admins(membership.company).filter(pk=membership.pk).exists()
    if is_admin:
        other_admins = company_active_admins(membership.company).exclude(pk=membership.pk)
        if not other_admins.exists():
            return None, "CANNOT_REMOVE_LAST_COMPANY_ADMIN"
    membership.delete()
    return True, None


def set_member_workspace_role(
    membership: "CompanyMember",
    role_code: str,
) -> Tuple[Optional["CompanyMember"], Optional[str]]:
    """
    Change a member's workspace role — the Company Admin's delegation tool.

    Invariants:
      - role must exist and be applicable to the company's type(s);
      - never-orphan: if this member is the company's SOLE admin (unified floor,
        see `_admin_floor_q`) and the new WorkspaceRole would strip their admin
        standing, refuse → CANNOT_DEMOTE_LAST_COMPANY_ADMIN (transfer first). A
        member on the is_system CompanyRole keeps admin standing regardless of the
        WorkspaceRole label, so relabeling them is never blocked.
    """
    role = WorkspaceRole.objects.filter(code=role_code).first()
    if not role:
        return None, "WORKSPACE_ROLE_NOT_FOUND"

    applicable = role.applicable_to_types.all()
    if applicable.exists():
        company_type_codes = set(membership.company.types.values_list("code", flat=True))
        allowed_codes = set(applicable.values_list("code", flat=True))
        if not (company_type_codes & allowed_codes):
            return None, "WORKSPACE_ROLE_NOT_APPLICABLE_TO_COMPANY_TYPE"

    currently_admin = (
        membership.is_active and company_active_admins(membership.company).filter(pk=membership.pk).exists()
    )
    would_stay_admin = bool(
        (membership.company_role_id and membership.company_role.is_system) or role.code == WorkspaceRoleCode.OWNER
    )
    if currently_admin and not would_stay_admin:
        other_admins = company_active_admins(membership.company).exclude(pk=membership.pk)
        if not other_admins.exists():
            return None, "CANNOT_DEMOTE_LAST_COMPANY_ADMIN"

    membership.role = role
    membership.save(update_fields=["role"])
    return membership, None


def toggle_user_active(
    user: CustomUser,
    requester: CustomUser,
) -> Tuple[Optional[CustomUser], Optional[str]]:
    """
    Toggle user's is_active flag. Prevents self-deactivation.
    Returns: (user, error_or_None)
    """
    if user.pk == requester.pk:
        return None, "CANNOT_DEACTIVATE_SELF"
    # Never-orphan (audit L3): deactivating the user disables their account platform-wide; if
    # they are the SOLE active admin of any company, that company would be left with no admin
    # (no one to manage team/billing). Block — transfer ownership first. "Admin" is the
    # unified is_system / legacy-OWNER floor (see `_admin_floor_q`), matching every other check.
    if user.is_active:  # about to deactivate
        admin_memberships = CompanyMember.objects.filter(_admin_floor_q(), user=user, is_active=True).select_related(
            "company"
        )
        for membership in admin_memberships:
            if not company_active_admins(membership.company).exclude(user=user).exists():
                return None, "CANNOT_DEACTIVATE_SOLE_COMPANY_ADMIN"
    was_active = user.is_active
    user.is_active = not was_active
    user.save(update_fields=["is_active"])
    log_admin_action(
        entity_type="user",
        entity_id=user.pk,
        action="Аккаунт деактивирован" if was_active else "Аккаунт активирован",
        detail=user.email,
        actor=requester,
        event_code="admin.user.deactivated" if was_active else "admin.user.activated",
        event_params={"email": user.email},
        before={"is_active": was_active},
        after={"is_active": user.is_active},
        # Деактивация отрезает человека от платформы — это и есть «удаление» в терминах
        # эталонов (Salesforce/Odoo), и оно обязано быть видно в журнале доступа.
        level="WARNING" if was_active else "SUCCESS",
    )
    return user, None
