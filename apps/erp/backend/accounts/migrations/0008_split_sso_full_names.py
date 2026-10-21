"""FIX-64 (N-03) — чинит имена, которые SSO-вход записал целиком в `first_name`.

До исправления `sso.exchange` при каждом входе писал claim `name` («Имя Фамилия») в `first_name`, не трогая
`last_name`: `get_full_name()` давал «Имя Фамилия Фамилия» (публичная КП, PDF, подписи договора, письма).
Правило то же, что у `integration.services.provision.split_full_name`: имя — первое слово, фамилия — остаток.

Меняются только испорченные записи (идемпотентно, повторный запуск ничего не меняет):
Дефект касался только сотрудников из CRM (есть сопоставление `CrmUserMapping`, имя пришло из токена), поэтому
оба правила применяются только к ним:
  1. `first_name` оканчивается на « <last_name>» — отрезаем повтор фамилии;
  2. `last_name` пуст, в `first_name` есть пробел — делим на имя и фамилию.
Остальные профили (заполненные вручную и пользователи без сопоставления) не трогаются.
"""

from django.db import migrations


def split_sso_full_names(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")

    # 1. «Имя Фамилия» + last_name «Фамилия» → first_name «Имя».
    for user in CustomUser.objects.exclude(last_name="").filter(crm_user_mapping__isnull=False).iterator():
        suffix = f" {user.last_name}"
        if user.first_name.endswith(suffix) and user.first_name.strip() != user.last_name:
            user.first_name = user.first_name[: -len(suffix)].strip()
            user.save(update_fields=["first_name"])

    # 2. Полное имя в first_name без фамилии у сотрудников CRM.
    for user in CustomUser.objects.filter(last_name="", crm_user_mapping__isnull=False).iterator():
        first, _, last = user.first_name.strip().partition(" ")
        if last.strip():
            user.first_name, user.last_name = first[:150], last.strip()[:150]
            user.save(update_fields=["first_name", "last_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_companyrole_managed_by_crm"),
        ("integration", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(split_sso_full_names, migrations.RunPython.noop),
    ]
