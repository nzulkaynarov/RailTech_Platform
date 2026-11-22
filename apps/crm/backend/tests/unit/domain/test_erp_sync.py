"""Синхронизация пользователя CRM с ERP (FIX-11): таблица кейсов «до → после → действие»."""

from dataclasses import replace

import pytest

from app.domain.erp_sync import AccessState, access_audit_action, erp_sync_status, sync_action

CRM_ONLY = AccessState(("crm",), True, ("manager",), "Иван")
WITH_ERP = replace(CRM_ONLY, platform_access=("crm", "erp"))


@pytest.mark.parametrize(
    ("before", "after", "action", "audit"),
    [
        pytest.param(CRM_ONLY, WITH_ERP, "provision", "platform_access.granted", id="grant"),
        pytest.param(WITH_ERP, CRM_ONLY, "revoke", "platform_access.revoked", id="revoke"),
        pytest.param(CRM_ONLY, CRM_ONLY, None, None, id="nothing-changed"),
        pytest.param(WITH_ERP, WITH_ERP, None, None, id="access-kept"),
        pytest.param(
            WITH_ERP, replace(WITH_ERP, is_active=False), "revoke", None, id="deactivated-with-erp"
        ),
        pytest.param(
            replace(WITH_ERP, is_active=False), WITH_ERP, "provision", None, id="reactivated"
        ),
        pytest.param(
            CRM_ONLY, replace(CRM_ONLY, is_active=False), None, None, id="deactivated-crm-only"
        ),
        pytest.param(
            CRM_ONLY,
            replace(WITH_ERP, is_active=False),
            None,
            "platform_access.granted",
            id="grant-to-inactive-waits-for-activation",
        ),
        pytest.param(
            WITH_ERP, replace(WITH_ERP, roles=("admin",)), "provision", None, id="role-changed"
        ),
        pytest.param(
            replace(WITH_ERP, roles=("manager", "viewer")),
            replace(WITH_ERP, roles=("viewer", "manager")),
            None,
            None,
            id="roles-reordered-same-set",
        ),
        pytest.param(
            WITH_ERP, replace(WITH_ERP, full_name="Пётр"), "provision", None, id="name-changed"
        ),
        pytest.param(
            CRM_ONLY, replace(CRM_ONLY, roles=("admin",)), None, None, id="role-changed-crm-only"
        ),
        pytest.param(
            WITH_ERP,
            replace(WITH_ERP, erp_role_codes=("FINANCE",)),
            "provision",
            None,
            id="erp-roles-chosen",
        ),
        pytest.param(
            replace(WITH_ERP, erp_role_codes=("FINANCE", "HEAD")),
            replace(WITH_ERP, erp_role_codes=("FINANCE",)),
            "provision",
            None,
            id="erp-role-dropped",
        ),
        pytest.param(
            replace(WITH_ERP, erp_role_codes=("CALCULATION", "FINANCE")),
            replace(WITH_ERP, erp_role_codes=("FINANCE", "CALCULATION")),
            None,
            None,
            id="erp-roles-reordered-same-set",
        ),
        pytest.param(
            CRM_ONLY,
            replace(CRM_ONLY, erp_role_codes=("HEAD",)),
            None,
            None,
            id="erp-roles-without-erp-access-wait",
        ),
        pytest.param(
            replace(WITH_ERP, erp_role_codes=("HEAD",)),
            replace(CRM_ONLY, erp_role_codes=("HEAD",)),
            "revoke",
            "platform_access.revoked",
            id="revoke-keeps-the-chosen-roles-for-later",
        ),
        pytest.param(
            replace(WITH_ERP, is_active=False),
            CRM_ONLY,
            "revoke",
            "platform_access.revoked",
            id="revoke-of-inactive-is-still-sent",
        ),
        pytest.param(
            WITH_ERP,
            replace(WITH_ERP, platform_role_ids=(3,)),
            "provision",
            None,
            id="platform-roles-chosen-change-erp-rights",
        ),
        pytest.param(
            replace(WITH_ERP, platform_role_ids=(3, 4)),
            replace(WITH_ERP, platform_role_ids=(4, 3)),
            None,
            None,
            id="platform-roles-reordered-same-set",
        ),
        pytest.param(
            replace(WITH_ERP, platform_role_ids=(3,)),
            replace(WITH_ERP, platform_role_ids=(3, 4)),
            "provision",
            None,
            id="platform-role-added-with-same-erp-roles",
        ),
    ],
)
def test_sync_decision(
    before: AccessState, after: AccessState, action: str | None, audit: str | None
) -> None:
    assert sync_action(before, after) == action
    assert access_audit_action(before, after) == audit


@pytest.mark.parametrize(
    ("has_erp", "is_active", "error", "pending", "provisioned", "status"),
    [
        # 1. ошибка важнее всего
        pytest.param(True, True, "boom", True, True, "error", id="error-first"),
        pytest.param(False, False, "boom", False, False, "error", id="error-even-inapplicable"),
        # 2. нет доступа или не активен — выдача не в счёт, отзыв в очереди не «выдаётся»
        pytest.param(False, True, None, True, True, "not_applicable", id="no-access"),
        pytest.param(True, False, None, True, True, "not_applicable", id="disabled-revoke-queued"),
        # 3. факт есть — ок, даже если задача (повторный провижининг) в очереди
        pytest.param(True, True, None, False, True, "ok", id="fact"),
        pytest.param(True, True, None, True, True, "ok", id="fact-and-queued"),
        # 4. факта нет, задача в очереди — pending
        pytest.param(True, True, None, True, False, "pending", id="no-fact-queued"),
        # 5. факта нет и задачи нет — «не выдан»
        pytest.param(True, True, None, False, False, "error", id="no-fact-no-job"),
    ],
)
def test_erp_sync_status_derives_from_the_fact(
    has_erp: bool,
    is_active: bool,
    error: str | None,
    pending: bool,
    provisioned: bool,
    status: str,
) -> None:
    assert (
        erp_sync_status(
            has_erp=has_erp,
            is_active=is_active,
            error=error,
            pending=pending,
            provisioned=provisioned,
        )
        == status
    )
