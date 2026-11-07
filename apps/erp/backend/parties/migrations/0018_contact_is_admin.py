# Generated manually for J2 (Team & Trust)

from django.db import migrations, models


def set_default_admins(apps, schema_editor):
    Contact = apps.get_model("parties", "Contact")
    Company = apps.get_model("parties", "Company")
    for company in Company.objects.all():
        contacts = Contact.objects.filter(company=company)
        if contacts.exists() and not contacts.filter(is_admin=True).exists():
            primary = contacts.filter(is_primary=True).first()
            if primary:
                primary.is_admin = True
                primary.save(update_fields=["is_admin"])
            else:
                first = contacts.order_by("id").first()
                if first:
                    first.is_admin = True
                    first.save(update_fields=["is_admin"])


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0017_partnerapplication_contract_pdf_and_agreed"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="is_admin",
            field=models.BooleanField(
                default=False,
                help_text="Управляет командой компании и правами доступа в кабинете (J2, ADR-0022)",
                verbose_name="Администратор компании",
            ),
        ),
        migrations.RunPython(set_default_admins, reverse_code=migrations.RunPython.noop),
    ]

