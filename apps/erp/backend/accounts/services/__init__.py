"""services package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .auth import (
    change_user_password,
    reset_password,
    revoke_user_refresh_tokens,
    send_password_reset_email,
    verify_and_setup_password,
)
from .clients import create_offline_client, find_client_company
from .company_lifecycle import archive_company, can_delete_company, company_history_holders, unarchive_company
from .company_settings import get_company_settings, update_company_settings
from .document_profile import (
    get_document_profile,
    is_company_owner,
    update_document_profile,
    upload_document_profile_logo,
)
from .members import (
    add_company_member,
    can_delete_user,
    change_user_role,
    company_active_admins,
    create_platform_user,
    invite_workspace_member,
    remove_company_member,
    set_member_workspace_role,
    toggle_user_active,
)
from .permissions import (
    can_edit_quote_pricing,
    is_member_of,
    is_seller,
    member_has_permission,
    primary_seller_company_id,
    sees_all_deals,
)
from .roles import (
    assign_role_to_member,
    create_company_role,
    delete_company_role,
    list_roles_for_user,
    update_company_role,
)

__all__ = [
    "add_company_member",
    "change_user_password",
    "can_delete_user",
    "change_user_role",
    "create_platform_user",
    "company_active_admins",
    "get_company_settings",
    "update_company_settings",
    "get_document_profile",
    "invite_workspace_member",
    "is_company_owner",
    "update_document_profile",
    "upload_document_profile_logo",
    "is_member_of",
    "is_seller",
    "primary_seller_company_id",
    "sees_all_deals",
    "remove_company_member",
    "reset_password",
    "revoke_user_refresh_tokens",
    "send_password_reset_email",
    "set_member_workspace_role",
    "toggle_user_active",
    "verify_and_setup_password",
    "archive_company",
    "can_delete_company",
    "company_history_holders",
    "unarchive_company",
    "create_offline_client",
    "find_client_company",
    "can_edit_quote_pricing",
    "member_has_permission",
    "assign_role_to_member",
    "create_company_role",
    "delete_company_role",
    "list_roles_for_user",
    "update_company_role",
]
