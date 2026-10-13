"""Снять `is_staff` со всех, кто не суперпользователь и не член `system_engineers`.

Флаг раздавался бизнес-аккаунтам (сиды `core/data/seed_data.json`, ручные правки в Unfold) и до
волны 20-08 сам по себе открывал инженерную админку. Дверь теперь закрыта гейтом
(`core.admin_site.EngineeringAdminSite`), но флаг остаётся вводящей в заблуждение отметкой
«сотрудник платформы» в списках и фильтрах — и снова станет пропуском, если гейт когда-нибудь
ослабят. Приводим данные к схеме, которую миграция `0006_system_engineers_group` объявила ещё в
апреле: доступ = членство в группе, а не булево поле в строке пользователя.

Откат намеренно НЕ восстанавливает флаги: вернуть права «как было» без списка тех, у кого они
были осмысленны, — хуже, чем не вернуть ничего. Инженеру флаг ставит `manage.py grant_engineer`.
"""

from django.db import migrations

SYSTEM_ENGINEERS_GROUP = "system_engineers"


def strip_staff_flag(apps, schema_editor):
    User = apps.get_model("accounts", "CustomUser")
    Group = apps.get_model("auth", "Group")

    engineer_ids = set()
    group = Group.objects.filter(name=SYSTEM_ENGINEERS_GROUP).first()
    if group is not None:
        engineer_ids = set(group.user_set.values_list("id", flat=True))

    stale = User.objects.filter(is_staff=True, is_superuser=False).exclude(id__in=engineer_ids)
    stale.update(is_staff=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0044_purge_retired_roles_after_core_seed"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(strip_staff_flag, reverse_code=migrations.RunPython.noop),
    ]
