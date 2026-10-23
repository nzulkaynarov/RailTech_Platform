"""Журнал шины rt_bus в инженерной админке (B3, ADR-0014): доставки, входящие, outbox, паузы подписчиков.

Заменяет журнал вебхуков ERP → CRM. Здесь инженер видит, что и когда ушло подписчикам (статус, попытки, код ответа,
ошибка) и что пришло от чужих сервисов, и может повторить: «Повторить» (доставка из `dead` или ожидающая, попытки с нуля) и
«Повторить все dead» по подписчикам выбранных строк; для входящих — «Повторить обработку» (`failed`/`skipped`). Действия —
только суперпользователю, с экраном подтверждения, причиной и записью в журнал доступа (`superuser_only_action`); то же из
командной строки — `manage.py bus_retry`. Сами строки журнала неизменяемы: доставкой правит шина, не человек.
"""

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from rt_bus.django.models import Delivery, Inbox, Outbox, SubscriberState
from unfold.admin import ModelAdmin

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from .bus import get_bus


class _BusJournalAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """Журнал шины целиком только для чтения, даже суперпользователю: правка строки расходится с тем, что видел подписчик."""

    list_per_page = 50
    list_filter_submit = True

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Delivery)
class BusDeliveryAdmin(_BusJournalAdmin):
    list_display = (
        "event_type",
        "subscriber",
        "status",
        "attempts",
        "last_status_code",
        "last_attempt_at",
        "next_attempt_at",
        "created_at",
    )
    list_filter = ("status", "subscriber", "event_type")
    search_fields = ("event_id", "event_type", "last_error")
    ordering = ("-created_at",)
    actions = ["retry_selected", "retry_all_dead_of_subscribers"]

    @superuser_only_action(_("Повторить доставку"))
    def retry_selected(self, request, queryset):
        # `dead` и ожидающие: `delivered` повторять незачем (подписчик уже принял, дубль гасит его inbox).
        bus = get_bus()
        requeued = sum(
            1 for pk in queryset.exclude(status="delivered").values_list("pk", flat=True) if bus.retry_delivery(pk)
        )
        self.message_user(
            request,
            _("Поставлено на повторную доставку: %(count)d.") % {"count": requeued},
            level=messages.SUCCESS if requeued else messages.WARNING,
        )

    @superuser_only_action(_("Повторить все dead выбранных подписчиков"))
    def retry_all_dead_of_subscribers(self, request, queryset):
        bus = get_bus()
        total = sum(
            bus.retry_all_dead(subscriber) for subscriber in sorted(set(queryset.values_list("subscriber", flat=True)))
        )
        self.message_user(
            request,
            _("Поставлено на повторную доставку (dead): %(count)d.") % {"count": total},
            level=messages.SUCCESS if total else messages.WARNING,
        )


@admin.register(Inbox)
class BusInboxAdmin(_BusJournalAdmin):
    list_display = ("type", "publisher", "status", "attempts", "received_at", "processed_at")
    list_filter = ("status", "publisher", "type")
    search_fields = ("event_id", "type", "subject", "error")
    ordering = ("-received_at",)
    actions = ["retry_selected"]

    @superuser_only_action(_("Повторить обработку"))
    def retry_selected(self, request, queryset):
        bus = get_bus()
        requeued = sum(
            1
            for event_id in queryset.filter(status__in=["failed", "skipped"]).values_list("pk", flat=True)
            if bus.retry_inbox(event_id)
        )
        self.message_user(
            request,
            _("Поставлено на повторную обработку: %(count)d.") % {"count": requeued},
            level=messages.SUCCESS if requeued else messages.WARNING,
        )


@admin.register(Outbox)
class BusOutboxAdmin(_BusJournalAdmin):
    list_display = ("type", "subject", "created_at", "dispatched_at")
    list_filter = ("type",)
    search_fields = ("id", "type", "subject", "correlation_id")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


@admin.register(SubscriberState)
class BusSubscriberStateAdmin(_BusJournalAdmin):
    list_display = ("subscriber", "consecutive_failures", "paused_until", "last_success_at", "last_failure_at")
    ordering = ("subscriber",)
