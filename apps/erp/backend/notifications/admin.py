from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from .models import EmailLog, EmailTemplate, Notification, NotificationType


@admin.register(NotificationType)
class NotificationTypeAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 15


@admin.register(Notification)
class NotificationAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("title", "user", "type", "is_read", "read_badge", "created_at")
    list_filter = ("type", "is_read", "created_at")
    list_filter_submit = True
    search_fields = ("title", "message", "user__email")
    autocomplete_fields = ["user", "type", "deal"]
    readonly_fields = ("created_at",)
    actions = ["mark_as_read"]
    list_per_page = 30
    list_select_related = ("user", "type")
    show_full_result_count = False

    @display(
        description=_("Прочитано"),
        label={True: "success", False: "danger"},
    )
    def read_badge(self, obj):
        return obj.is_read

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("title", "type"),
                    "message",
                    ("user", "deal"),
                    ("link", "is_read"),
                    "created_at",
                ),
            },
        ),
    )

    @superuser_only_action(_("Пометить прочитанными"))
    def mark_as_read(self, request, queryset):
        # Действие правит ЧУЖИЕ уведомления: сервис снимает флаг по всей выборке, без всякой
        # привязки к владельцу. Из девяти массовых действий админки это было единственное без
        # `@superuser_only_action` — не-суперпользователь гасил колокольчик у арендаторов, и
        # человек переставал видеть, что счёт выставлен или акт ждёт подтверждения.
        from . import services

        updated = services.mark_notifications_read(queryset)
        self.message_user(request, _("%(count)d прочитано.") % {"count": updated})


@admin.register(EmailLog)
class EmailLogAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """Audit log of every outbound email. Populated by notifications.emails.send_templated_email."""

    list_display = (
        "created_at",
        "status_badge",
        "template",
        "channel",
        "subject",
        "recipients_short",
        "user",
    )
    list_filter = ("status", "channel", "template", "created_at")
    list_filter_submit = True
    search_fields = ("subject", "from_email", "user__email", "error")
    autocomplete_fields = ["user"]
    date_hierarchy = "created_at"
    list_per_page = 50
    list_select_related = ("user",)
    show_full_result_count = False
    readonly_fields = (
        "template",
        "channel",
        "subject",
        "from_email",
        "to_emails",
        "user",
        "body_text",
        "body_html_preview",
        "status",
        "error",
        "created_at",
    )

    fieldsets = (
        (
            _("Метаданные"),
            {
                "fields": (
                    ("template", "channel"),
                    ("status", "created_at"),
                    ("from_email", "user"),
                    "to_emails",
                    "subject",
                ),
            },
        ),
        (
            _("Тело письма"),
            {
                "fields": ("body_html_preview", "body_text"),
            },
        ),
        (
            _("Ошибка"),
            {
                "fields": ("error",),
                "classes": ("collapse",),
            },
        ),
    )

    @display(
        description=_("Статус"),
        label={
            EmailLog.STATUS_QUEUED: "info",
            EmailLog.STATUS_SENT: "success",
            EmailLog.STATUS_FAILED: "danger",
        },
    )
    def status_badge(self, obj):
        return obj.status

    @display(description=_("Кому"))
    def recipients_short(self, obj):
        if not obj.to_emails:
            return "—"
        head = ", ".join(obj.to_emails[:2])
        extra = len(obj.to_emails) - 2
        return f"{head} (+{extra})" if extra > 0 else head

    @display(description=_("HTML-превью"))
    def body_html_preview(self, obj):
        if not obj.body_html:
            return _("— (только plain-text)")
        # Render the raw HTML inside an isolated iframe via srcdoc — email CSS
        # routinely uses absolute widths and inline colors that would otherwise
        # leak into the admin theme.
        return format_html(
            '<iframe srcdoc="{}" sandbox '
            'style="width:100%; min-height:480px; border:1px solid #e5e7eb; '
            'border-radius:8px; background:#ffffff;"></iframe>',
            obj.body_html,
        )


@admin.register(EmailTemplate)
class EmailTemplateAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """DB-editable email templates. Primary editor is the React Platform-Operator
    admin; this Unfold registration is an engineer-side fallback.

    Единственная админка этого файла, оставшаяся БЕЗ readonly-миксина (замер 25-08): активная
    строка немедленно подменяет файловый шаблон для ВСЕХ получателей платформы, то есть текст
    письма клиенту менялся правкой не-суперпользователя. Волна #599 закрыла эту дверь со
    стороны API (`platform.settings`) — здесь закрывается вторая, со стороны Unfold.
    """

    list_display = ("key", "subject", "is_active", "updated_by", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("key", "subject")
    readonly_fields = ("updated_by", "updated_at")
    list_per_page = 30

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
