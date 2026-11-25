"""СОТР-1: `can_sell` сотрудников из CRM по их правам (одноразовая миграция данных).

До этого провижининг флаг не выставлял, и он оставался «да» у всех: бухгалтер, снабженец и администратор получали в
колокольчик оплату, акт и просрочку по всем сделкам. Теперь продавец — тот, у кого последним провижинингом пришло право
`deal.manage` (и не суперпользователь), остальным — «нет». Затрагиваются основные членства сотрудников с сопоставлением
CRM; членства без снимка прав считаются «без прав» (как в `attach_provisioned_users`).

Обратная миграция возвращает «да» тем же членствам (так было до неё: значение по умолчанию).
"""

from django.db import migrations


def _is_seller(role, permissions):
    return role != "admin" and "deal.manage" in (permissions or [])


def forwards(apps, schema_editor):
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    CrmUserMapping = apps.get_model("integration", "CrmUserMapping")
    for mapping in CrmUserMapping.objects.all().iterator():
        snapshot = mapping.provision_snapshot or {}
        sells = _is_seller(snapshot.get("role"), snapshot.get("permissions"))
        CompanyMember.objects.filter(user_id=mapping.user_id, is_primary=True).update(can_sell=sells)


def backwards(apps, schema_editor):
    CompanyMember = apps.get_model("accounts", "CompanyMember")
    CrmUserMapping = apps.get_model("integration", "CrmUserMapping")
    user_ids = list(CrmUserMapping.objects.values_list("user_id", flat=True))
    CompanyMember.objects.filter(user_id__in=user_ids, is_primary=True).update(can_sell=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_contract_template_approval_permission"),
        ("integration", "0014_commercial_signing_visas"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
