from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display
from .models import NotificationType, Notification


@admin.register(NotificationType)
class NotificationTypeAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ("title", "user", "type", "is_read", "read_badge", "created_at")
    list_filter = ("type", "is_read", "created_at")
    list_filter_submit = True
    list_editable = ["is_read"]
    search_fields = ("title", "message", "user__email")
    autocomplete_fields = ["user", "type", "deal"]
    readonly_fields = ("created_at",)
    actions = ["mark_as_read"]
    list_per_page = 30

    @display(
        description=_("Прочитано"),
        label={True: "success", False: "danger"},
    )
    def read_badge(self, obj):
        return obj.is_read

    fieldsets = (
        (None, {
            "fields": (
                ("title", "type"),
                "message",
                ("user", "deal"),
                ("link", "is_read"),
                "created_at",
            ),
        }),
    )

    @admin.action(description=_("Пометить прочитанными"))
    def mark_as_read(self, request, queryset):
        updated = queryset.filter(is_read=False).update(is_read=True)
        self.message_user(request, _("%(count)d прочитано.") % {"count": updated})
