from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import display
from .models import Attachment, DomainKeyword, ImportTask


@admin.register(Attachment)
class AttachmentAdmin(ModelAdmin):
    list_display = ("original_filename", "uploaded_by", "parent_entity", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("original_filename", "uploaded_by__email")
    readonly_fields = ("uploaded_at",)
    autocomplete_fields = ["uploaded_by", "product", "deal", "message", "quote", "company"]
    list_per_page = 30

    @display(description=_("Привязка"))
    def parent_entity(self, obj):
        if obj.product:
            return f"Товар: {obj.product}"
        if obj.deal:
            return f"Сделка: {obj.deal}"
        if obj.quote:
            return f"КП: {obj.quote}"
        if obj.company:
            return f"Компания: {obj.company}"
        if obj.message:
            return f"Сообщение #{obj.message_id}"
        return "—"

    fieldsets = (
        (None, {
            "fields": (
                ("file", "original_filename"),
                ("uploaded_by", "uploaded_at"),
            ),
        }),
        (_("Привязка"), {
            "classes": ["tab"],
            "fields": ("product", "deal", "quote", "company", "message"),
        }),
    )


@admin.register(DomainKeyword)
class DomainKeywordAdmin(ModelAdmin):
    list_display = ("keyword", "domain_type")
    list_filter = ("domain_type",)
    search_fields = ("keyword",)
    autocomplete_fields = ["domain_type"]
    list_per_page = 30

    fieldsets = (
        (None, {"fields": (("keyword", "domain_type"),)}),
    )


@admin.register(ImportTask)
class ImportTaskAdmin(ModelAdmin):
    list_display = ("celery_task_id", "type_badge", "owner", "deal", "created_at")
    list_filter = ("task_type", "created_at")
    list_filter_submit = True
    search_fields = ("celery_task_id", "owner__email", "deal__title")
    readonly_fields = ("celery_task_id", "task_type", "owner", "deal", "created_at")
    list_per_page = 30

    @display(
        description=_("Тип"),
        label={
            "Импорт Excel в сделку": "info",
            "Импорт каталога": "success",
        },
    )
    def type_badge(self, obj):
        return obj.get_task_type_display()

    fieldsets = (
        (None, {
            "fields": (
                ("celery_task_id", "task_type"),
                ("owner", "deal"),
                "created_at",
            ),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
