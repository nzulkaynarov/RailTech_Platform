"""Текстовое «контактное лицо» компании → человек с отметкой «главный» (ADR-0028 п. 2).

Есть действующий человек с тем же именем (без учёта регистра) — главным становится он; нет — заводится с телефоном и
почтой компании. Текстовое поле очищается. Откат возвращает текст из имени главного человека; людей не удаляет.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    Contact = apps.get_model("parties", "Contact")
    for company in Company.objects.exclude(contact_person="").iterator():
        name = (company.contact_person or "").strip()
        if name:
            people = Contact.objects.filter(company_id=company.pk, archived_at__isnull=True)
            person = next((p for p in people if p.name.strip().casefold() == name.casefold()), None)
            if person is None:
                person = Contact.objects.create(
                    company_id=company.pk,
                    name=name[:255],
                    phone=(company.phone or "")[:50],
                    email=company.email or "",
                    is_primary=True,
                )
            elif not person.is_primary:
                person.is_primary = True
                person.save(update_fields=["is_primary"])
            Contact.objects.filter(company_id=company.pk, is_primary=True).exclude(pk=person.pk).update(
                is_primary=False
            )
        Company.objects.filter(pk=company.pk).update(contact_person="")


def backwards(apps, schema_editor):
    Company = apps.get_model("parties", "Company")
    Contact = apps.get_model("parties", "Contact")
    for person in Contact.objects.filter(is_primary=True, archived_at__isnull=True).order_by("company_id", "name"):
        Company.objects.filter(pk=person.company_id, contact_person="").update(contact_person=person.name[:255])


class Migration(migrations.Migration):
    dependencies = [("parties", "0026_partner_application_from_letter")]

    operations = [migrations.RunPython(forwards, backwards)]
