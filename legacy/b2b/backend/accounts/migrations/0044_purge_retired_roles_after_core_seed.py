"""Отставные системные роли не должны воскресать из-за порядка миграций.

`accounts/0019_purge_retired_system_roles` вычищает роли, выведенные ADR-0002
(GUEST / CLIENT / EMPLOYEE / ACCOUNT_MANAGER / SALES_MANAGER), но `core/0002_seed_enterprise_lookups`
их СЕЕТ — и между этими миграциями не объявлено зависимости. На боевой базе порядок сложился
удачно (там остались только ADMIN и USER), а на свежей — наоборот: сначала пург, потом сев.
Итог виден оператору: в реестре пользователей появляются вкладки-фильтры по ролям, которых
платформа не знает, подписанные сырыми ключами `roles.GUEST` и т. п. (ключей в i18n нет, потому
что роли выведены). Найдено прогоном глазами 19-08 на локальном стенде.

Лечение — порядок, а не косметика: эта миграция зависит ОТ ОБЕИХ и вычищает отставные роли
последней. Добавлять `roles.*` в переводы было бы хуже — это узаконило бы выведенные роли.
"""

from django.db import migrations

CANONICAL = ["ADMIN", "USER"]


def purge_retired_system_roles(apps, schema_editor):
    SystemRole = apps.get_model("accounts", "SystemRole")
    CustomUser = apps.get_model("accounts", "CustomUser")
    user_role = SystemRole.objects.filter(code="USER").first()
    if user_role:
        # Никого не оставляем без роли: перед удалением переводим на USER.
        CustomUser.objects.exclude(role__code__in=CANONICAL).exclude(role__isnull=True).update(role=user_role)
    SystemRole.objects.exclude(code__in=CANONICAL).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0043_document_wording_fields"),
        ("core", "0002_seed_enterprise_lookups"),
    ]
    operations = [migrations.RunPython(purge_retired_system_roles, migrations.RunPython.noop)]
