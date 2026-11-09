"""FX-6: у каждой компании с активными контактами — активный администратор.

`0018` выбирала любой контакт, в том числе архивный, а компании, созданные после неё (передача из CRM, заявка партнёра,
сотрудник в ERP), администратора не получали. Данные: архивным контактам флаг снимается, компаниям без активного
администратора назначается основной активный контакт, иначе самый ранний. Безопасна на непустой таблице: обновляет
только нужные строки. Обратный ход пуст: назначенный администратор остаётся (снять его значит оставить компанию без
администратора), схема не меняется.
"""

from django.db import migrations


def backfill_admins(apps, schema_editor):
    Contact = apps.get_model("parties", "Contact")
    Contact.objects.filter(is_admin=True, archived_at__isnull=False).update(
        is_admin=False
    )
    active = Contact.objects.filter(archived_at__isnull=True)
    with_admin = set(active.filter(is_admin=True).values_list("company_id", flat=True))
    seen = set()
    for contact in active.exclude(company_id__in=with_admin).order_by(
        "company_id", "-is_primary", "id"
    ):
        if contact.company_id in seen:
            continue
        seen.add(contact.company_id)
        Contact.objects.filter(pk=contact.pk).update(is_admin=True)


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0021_partnerapplication_applicant_contact_created"),
    ]

    operations = [
        migrations.RunPython(backfill_admins, reverse_code=migrations.RunPython.noop),
    ]
