"""Синхронизация пользователя CRM с ERP (FIX-11): таблица кейсов «до → после → действие»."""

from dataclasses import replace

import pytest

from app.domain.erp_sync import AccessState, access_audit_action, sync_action

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
            replace(WITH_ERP, is_active=False),
            CRM_ONLY,
            "revoke",
            "platform_access.revoked",
            id="revoke-of-inactive-is-still-sent",
        ),
    ],
)
def test_sync_decision(
    before: AccessState, after: AccessState, action: str | None, audit: str | None
) -> None:
    assert sync_action(before, after) == action
    assert access_audit_action(before, after) == audit
