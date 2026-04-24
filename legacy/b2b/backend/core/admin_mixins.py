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
    Forces a Django ModelAdmin into "inspection mode":

    - Add via UI: forbidden
    - Delete via UI: forbidden
    - Field editing in change form: forbidden (all fields become readonly)
    - View change form: ALLOWED (so engineer can inspect record)
    - Custom @admin.action handlers: ALLOWED only for superusers
      (use @superuser_only_action decorator)

    Override `inspection_editable_fields` (tuple) on the subclass to allow
    editing specific fields if absolutely necessary for emergency repair.
    """

    inspection_editable_fields: tuple = ()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        existing = list(super().get_readonly_fields(request, obj))

        if obj is None:
            return existing

        all_fields = [
            f.name for f in self.model._meta.get_fields()
            if not f.many_to_many and not f.one_to_many
        ]
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
            actions = {
                k: v for k, v in actions.items()
                if not hasattr(v[0], '__wrapped__')
            }
        return actions
