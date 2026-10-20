import contextlib

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from core.admin_mixins import ReadOnlyInspectionMixin
from core.models import SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    """
    Read-only inspection of SystemSetting singleton.
    Business users edit via React Admin /admin/settings.
    Engineers can inspect current values and pghistory audit trail here.
    """

    list_display = ("__str__", "vat_rate", "standard_margin", "maintenance_mode", "updated_at")

    fieldsets = (
        (
            _("Финансы"),
            {
                "fields": ("vat_rate", "standard_margin"),
            },
        ),
        (
            _("Платформа"),
            {
                "classes": ["tab"],
                "fields": ("platform_name", "maintenance_mode"),
            },
        ),
        (
            _("Безопасность"),
            {
                "classes": ["tab"],
                "fields": ("is_two_factor_required",),
            },
        ),
        (
            _("Системное"),
            {
                "classes": ["tab"],
                "fields": ("updated_at",),
            },
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# Расписание Celery Beat — платформенный механизм, а не справочник
#
# Замер 25-08: пользователь с ОДНИМ правом `view_periodictask` открывал список задач и одним
# POST'ом массового действия выключал платформенную задачу — без страницы подтверждения и без
# следа (`LogEntry` +0, pghistory эту модель не отслеживает). Причина в самой библиотеке: у
# всех четырёх массовых действий django_celery_beat `allowed_permissions = None`, поэтому
# Django их правами НЕ фильтрует — право на просмотр открывало запись.
#
# Молча выключаются недельный автосинк ТН ВЭД, напоминания об оплате и истечение подписок.
# Поэтому расписание перерегистрируется под тем же режимом, что и остальная инженерная
# админка: не-суперпользователю — только чтение, действия библиотеки ему не предлагаются.
# ──────────────────────────────────────────────────────────────────────────
from django_celery_beat.admin import ClockedScheduleAdmin as _ClockedScheduleAdmin  # noqa: E402
from django_celery_beat.admin import CrontabScheduleAdmin as _CrontabScheduleAdmin  # noqa: E402
from django_celery_beat.admin import PeriodicTaskAdmin as _PeriodicTaskAdmin  # noqa: E402
from django_celery_beat.models import (  # noqa: E402
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)


class _BeatReadOnlyMixin(ReadOnlyInspectionMixin):
    """Read-only inspection + отбор массовых действий по ПРАВУ, а не по обёртке.

    Родительский `get_actions` отсекает только действия с `__wrapped__` (наш декоратор
    `superuser_only_action`). Действия библиотеки его не несут, поэтому проходили насквозь.
    """

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            return {}
        return actions


class PeriodicTaskAdmin(_BeatReadOnlyMixin, _PeriodicTaskAdmin):
    pass


class CrontabScheduleAdmin(_BeatReadOnlyMixin, _CrontabScheduleAdmin):
    pass


class ClockedScheduleAdmin(_BeatReadOnlyMixin, _ClockedScheduleAdmin):
    pass


class IntervalScheduleAdmin(_BeatReadOnlyMixin, ModelAdmin):
    pass


class SolarScheduleAdmin(_BeatReadOnlyMixin, ModelAdmin):
    pass


# Библиотека регистрирует свои админки при импорте — перерегистрируем поверх.
for _model, _admin_class in (
    (PeriodicTask, PeriodicTaskAdmin),
    (CrontabSchedule, CrontabScheduleAdmin),
    (ClockedSchedule, ClockedScheduleAdmin),
    (IntervalSchedule, IntervalScheduleAdmin),
    (SolarSchedule, SolarScheduleAdmin),
):
    with contextlib.suppress(admin.sites.NotRegistered):
        admin.site.unregister(_model)
    admin.site.register(_model, _admin_class)
