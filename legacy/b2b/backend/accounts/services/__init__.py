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
from .clients import create_offline_client, find_client_company
from .company_settings import get_company_settings, update_company_settings
from .document_profile import (
    get_document_profile,
    is_company_owner,
    update_document_profile,
    upload_document_profile_logo,
)
from .entitlements import (
    consume_credit,
    entitlement_state,
    grant_entitlement,
    has_entitlement,
    is_demo,
    quote_export_entitled,
    quote_send_entitled,
)
from .kyc import bulk_verify_kyc, delete_kyc_document, upload_kyc_document, verify_company_kyc
from .members import (
    add_company_member,
    change_user_role,
    company_active_admins,
    invite_workspace_member,
    remove_company_member,
    set_member_workspace_role,
    toggle_user_active,
)
from .operators import (
    assign_operator_role,
    create_operator_role,
    delete_operator_role,
    list_operator_roles,
    update_operator_role,
)
from .permissions import (
    acting_context,
    assert_seller_can_operate,
    can_edit_quote_pricing,
    company_has_operational_subscription,
    is_member_of,
    is_platform_admin_viewer,
    is_seller,
    member_has_permission,
    operator_has_permission,
    primary_seller_company_id,
    seller_acting_company_ids,
    seller_can_access_deal,
    seller_company_routed_to_deal,
    seller_sees_all_deals,
    seller_visible_deal_ids,
)
from .profile import submit_company_profile
from .roles import (
    assign_role_to_member,
    create_company_role,
    delete_company_role,
    list_roles_for_user,
    update_company_role,
)
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
    "assign_operator_role",
    "bulk_approve_role_applications",
    "bulk_reject_role_applications",
    "bulk_verify_kyc",
    "change_subscription_status",
    "change_user_password",
    "change_user_role",
    "check_and_expire_subscriptions",
    "company_active_admins",
    "company_has_operational_subscription",
    "consume_credit",
    "entitlement_state",
    "grant_entitlement",
    "has_entitlement",
    "is_demo",
    "quote_export_entitled",
    "quote_send_entitled",
    "create_operator_role",
    "create_pending_user",
    "delete_operator_role",
    "delete_kyc_document",
    "ensure_trial_subscription",
    "get_company_settings",
    "update_company_settings",
    "get_document_profile",
    "invite_workspace_member",
    "is_company_owner",
    "update_document_profile",
    "upload_document_profile_logo",
    "is_member_of",
    "is_platform_admin_viewer",
    "is_seller",
    "list_operator_roles",
    "operator_has_permission",
    "primary_seller_company_id",
    "update_operator_role",
    "seller_can_access_deal",
    "seller_sees_all_deals",
    "seller_visible_deal_ids",
    "record_subscription_payment",
    "reject_role_application",
    "remove_company_member",
    "reset_password",
    "revoke_user_refresh_tokens",
    "send_password_reset_email",
    "set_member_workspace_role",
    "submit_company_profile",
    "toggle_user_active",
    "upload_kyc_document",
    "verify_and_setup_password",
    "verify_company_kyc",
    "create_offline_client",
    "find_client_company",
    "can_edit_quote_pricing",
    "member_has_permission",
    "seller_acting_company_ids",
    "seller_company_routed_to_deal",
    "assign_role_to_member",
    "create_company_role",
    "delete_company_role",
    "list_roles_for_user",
    "update_company_role",
]
