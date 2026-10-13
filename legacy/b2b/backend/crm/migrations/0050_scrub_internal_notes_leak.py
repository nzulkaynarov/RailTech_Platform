from django.db import migrations

# LEAK FIX (pre-merge audit): quote.notes is rendered verbatim in the CLIENT-facing КП PDF
# («Примечания»). Three service paths used to append INTERNAL text there — the platform-admin
# force-override reason + admin EMAIL ("[FORCE_ADMIN] admin@…: …"), the rework reason on
# send-back ("Возврат на доработку: …"), and the client-rejection reason ("Причина отказа: …").
# The code paths are fixed to log to the audit trail instead; this migration scrubs the lines
# already sitting in existing quotes so their PDFs stop leaking. Client-typed notes are kept.

LEAK_PREFIXES = ("[FORCE_ADMIN]", "Возврат на доработку:", "Причина отказа:")


def scrub_notes(apps, schema_editor):
    Quote = apps.get_model("crm", "Quote")
    for quote in Quote.objects.exclude(notes="").exclude(notes__isnull=True).iterator():
        lines = (quote.notes or "").splitlines()
        kept = [line for line in lines if not line.strip().startswith(LEAK_PREFIXES)]
        cleaned = "\n".join(kept).strip()
        if cleaned != (quote.notes or "").strip():
            quote.notes = cleaned
            quote.save(update_fields=["notes"])


def noop(apps, schema_editor):
    """Irreversible — we never restore leaked internal text into a client field."""


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0049_alter_quotecharge_options_and_more"),
    ]

    operations = [
        migrations.RunPython(scrub_notes, noop),
    ]
