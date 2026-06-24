"""services package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .applications import (
    approve_role_application,
    bulk_approve_role_applications,
    bulk_reject_role_applications,
    reject_role_application,
)
from .auth import (
    change_user_password,
    create_pending_user,
    reset_password,
    revoke_user_refresh_tokens,
    send_password_reset_email,
    verify_and_setup_password,
)
from .kyc import bulk_verify_kyc, delete_kyc_document, upload_kyc_document, verify_company_kyc
from .members import (
    add_company_member,
    change_user_role,
    company_active_admins,
    invite_workspace_member,
    remove_company_member,
    toggle_user_active,
)
from .permissions import (
    acting_context,
    assert_seller_can_operate,
    company_has_operational_subscription,
    is_member_of,
    is_platform_admin_viewer,
    is_seller,
    primary_seller_company_id,
    seller_sees_all_deals,
)
from .profile import submit_company_profile
from .subscriptions import (
    change_subscription_status,
    check_and_expire_subscriptions,
    ensure_trial_subscription,
    record_subscription_payment,
)

__all__ = [
    "acting_context",
    "add_company_member",
    "approve_role_application",
    "assert_seller_can_operate",
    "bulk_approve_role_applications",
    "bulk_reject_role_applications",
    "bulk_verify_kyc",
    "change_subscription_status",
    "change_user_password",
    "change_user_role",
    "check_and_expire_subscriptions",
    "company_active_admins",
    "company_has_operational_subscription",
    "create_pending_user",
    "delete_kyc_document",
    "ensure_trial_subscription",
    "invite_workspace_member",
    "is_member_of",
    "is_platform_admin_viewer",
    "is_seller",
    "primary_seller_company_id",
    "seller_sees_all_deals",
    "record_subscription_payment",
    "reject_role_application",
    "remove_company_member",
    "reset_password",
    "revoke_user_refresh_tokens",
    "send_password_reset_email",
    "submit_company_profile",
    "toggle_user_active",
    "upload_kyc_document",
    "verify_and_setup_password",
    "verify_company_kyc",
]
