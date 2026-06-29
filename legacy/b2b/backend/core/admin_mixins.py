"""
Admin mixins for restricting Django Unfold ModelAdmin to inspection mode.

Per ADR-0001:
- Django Unfold is the engineering / DBA inspection tool, not a daily-use admin.
- Business operations live in React Admin and DRF endpoints.
- Bulk admin actions remain as emergency back-door for superusers only.

Usage:
    from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

    @admin.register(Deal)
    class DealAdmin(ReadOnlyInspectionMixin, ModelAdmin):
        actions = ["close_deal"]

        @superuser_only_action(_("[Emergency] Закрыть сделку"))
        def close_deal(self, request, queryset):
            ...
"""

from functools import wraps

from django.contrib import admin
from django.utils.translation import gettext_lazy as _


def superuser_only_action(description):
    """
    Decorator for admin actions that should only be available to superusers.
    Non-superusers won't see the action in the dropdown.

    Usage:
        @superuser_only_action(_("[Emergency] Подтвердить KYC"))
        def verify_kyc(self, request, queryset):
            ...
    """

    def decorator(func):
        @admin.action(description=description)
        @wraps(func)
        def wrapper(self, request, queryset):
            if not request.user.is_superuser:
                self.message_user(
                    request,
                    _("Только суперпользователь может выполнить это действие."),
                    level="error",
                )
                return
            return func(self, request, queryset)

        return wrapper

    return decorator


class ReadOnlyInspectionMixin:
    """
    Inspection-mode guard for Django Unfold ModelAdmin.

    RULE CHANGE (2026-06-29, owner directive): the **superuser** (Platform Engineer) now
    has FULL privileges in Unfold — add / change / delete — for direct data administration.
    Unfold is no longer a read-only inspection tool for the superuser.

    AUDIT SCOPE (be precise — do NOT overclaim): django-pghistory triggers capture changes
    ONLY for the tracked business models — Deal, Quote, QuoteItem, Contract, Invoice, Payment,
    Act (and SystemSetting). Mutations to OTHER models (Company, SupplierSubscription,
    CompanyRoleApplication, Fulfillment, Product, SupplierOffer, …) are NOT history-tracked.
    Direct edits here also BYPASS service-layer side effects (FSM transitions, KYC/subscription
    emails, document-number minting, invoice.amount_paid recompute) — for those, prefer the
    React Operator pages / DRF services / @superuser_only_action handlers, which are audited.
    A handful of admins therefore keep `has_add_permission=False` (Contract/Invoice/Act/Payment)
    because raw creation produces structurally-broken rows (empty unique number / stale balance).

    NON-superuser staff (should any be granted Django admin access) remain in read-only
    inspection mode:
    - Add / Delete via UI: forbidden
    - Field editing in change form: forbidden (all fields become readonly)
    - View change form: ALLOWED (so they can inspect a record)
    Override `inspection_editable_fields` (tuple) to allow specific fields for such staff.
    Custom @admin.action handlers remain superuser-only (@superuser_only_action).
    """

    inspection_editable_fields: tuple = ()

    def has_add_permission(self, request):
        return bool(getattr(request.user, "is_superuser", False))

    def has_delete_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_superuser", False))

    def get_readonly_fields(self, request, obj=None):
        existing = list(super().get_readonly_fields(request, obj))

        # Superuser edits freely (full privileges); only non-superuser staff are locked
        # down to read-only inspection.
        if getattr(request.user, "is_superuser", False):
            return existing

        if obj is None:
            return existing

        all_fields = [f.name for f in self.model._meta.get_fields() if not f.many_to_many and not f.one_to_many]
        editable = set(self.inspection_editable_fields)
        for name in all_fields:
            if name not in editable and name not in existing:
                existing.append(name)
        return existing

    def get_actions(self, request):
        """Hide business actions from non-superusers."""
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            # Keep only built-in actions (like select all)
            actions = {k: v for k, v in actions.items() if not hasattr(v[0], "__wrapped__")}
        return actions
