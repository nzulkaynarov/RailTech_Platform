"""
Admin mixins for restricting Django Unfold ModelAdmin to inspection mode.

Per ADR-0001:
- Django Unfold is the engineering / DBA inspection tool, not a daily-use admin.
- Business operations live in React Admin and DRF endpoints.
- Bulk admin actions (which call `services.py` functions) remain available
  as a back-door for engineers, but inline form editing is forbidden.

Usage:
    from core.admin_mixins import ReadOnlyInspectionMixin

    @admin.register(Deal)
    class DealAdmin(ReadOnlyInspectionMixin, ModelAdmin):
        ...
"""
from django.contrib import admin


class ReadOnlyInspectionMixin:
    """
    Forces a Django ModelAdmin into "inspection mode":

    - Add via UI: forbidden
    - Delete via UI: forbidden
    - Field editing in change form: forbidden (all fields become readonly)
    - View change form: ALLOWED (so engineer can inspect record)
    - Custom @admin.action handlers: ALLOWED (they call service functions
      that contain authorized business logic)

    Override `inspection_editable_fields` (tuple) on the subclass to allow
    editing specific fields if absolutely necessary for emergency repair.
    """

    inspection_editable_fields: tuple = ()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        # Start from whatever the subclass already defined
        existing = list(super().get_readonly_fields(request, obj))

        if obj is None:
            # Add form view (shouldn't happen since add is disabled, but be defensive)
            return existing

        # Mark every concrete field readonly except whitelisted ones
        all_fields = [f.name for f in self.model._meta.get_fields() if not f.many_to_many and not f.one_to_many]
        editable = set(self.inspection_editable_fields)
        for name in all_fields:
            if name not in editable and name not in existing:
                existing.append(name)
        return existing
