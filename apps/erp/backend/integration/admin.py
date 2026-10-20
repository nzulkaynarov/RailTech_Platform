"""Журнал исходящих вебхуков ERP → CRM в инженерной админке (FIX-33, CONTRACTS §3, аудит I-7).

Ретраи ERP: 1, 5, 30 мин, 2, 6, 24 ч; после них событие остаётся `FAILED` — «журнал с ручным повтором».
Здесь инженер видит, что и когда ушло в CRM (статус, число попыток, ответ CRM, текст ошибки, тело и
заголовки) и может повторить доставку: действие «Повторить» — только суперпользователю, с экраном
подтверждения, причиной и записью в журнал доступа (`superuser_only_action`).

Сама строка журнала неизменяема даже для суперпользователя: тело события подписано и уже частично
принято CRM, правка задним числом разошлась бы с тем, что видела CRM.
"""

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from .models import IntegrationWebhookEvent, WebhookEventStatus
from .tasks import redeliver_event


@admin.register(IntegrationWebhookEvent)
class IntegrationWebhookEventAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = (
        "event_id",
        "event_type",
        "status",
        "attempts",
        "response_status",
        "last_attempt_at",
        "next_attempt_at",
        "created_at",
    )
    list_filter = ("status", "event_type", "created_at")
    list_filter_submit = True
    search_fields = ("event_id", "event_type", "last_error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ["redeliver_selected"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Смотреть журнал можно (право `view_*` даёт Django отдельно), править — нельзя никому.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @superuser_only_action(_("Повторить доставку в CRM"))
    def redeliver_selected(self, request, queryset):
        # Повторяем FAILED и «зависшие» PENDING. Пропускаем: SENT (CRM приняла, повтор плодил бы дубли в её
        # журнале) и PENDING, который ждёт СВОЕГО ретрая (`next_attempt_at` в будущем): второй запуск
        # завёл бы параллельную цепочку ретраев рядом с уже запланированной.
        now = timezone.now()
        requeued = skipped = 0
        for event in queryset:
            waiting = (
                event.status == WebhookEventStatus.PENDING
                and event.next_attempt_at is not None
                and event.next_attempt_at > now
            )
            if event.status == WebhookEventStatus.SENT or waiting:
                skipped += 1
                continue
            if redeliver_event(event.pk) is not None:
                requeued += 1
        if requeued:
            self.message_user(
                request,
                _("Поставлено на повторную доставку: %(count)d.") % {"count": requeued},
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                _("Пропущено (уже доставлено или ждёт своего повтора): %(count)d.") % {"count": skipped},
                level=messages.WARNING,
            )
