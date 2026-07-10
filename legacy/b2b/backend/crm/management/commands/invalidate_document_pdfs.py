"""Invalidate cached document PDFs so they re-render with the CURRENT template.

Document PDFs (КП / договор / инвойс / акт) are rendered once and stored in `pdf_file`; every
later download streams that cached file. After a template/design change, EXISTING documents keep
serving the old PDF until their cache is cleared — clearing `pdf_file` makes the next open
re-render on demand (ARCH-03 202-pattern) with the new template.

    docker compose exec backend python manage.py invalidate_document_pdfs --dry-run
    docker compose exec backend python manage.py invalidate_document_pdfs --type quote --sent-only
    docker compose exec backend python manage.py invalidate_document_pdfs --since 2026-06-01

⚠ Prod data operation — verify you are on the intended DB first (`printenv DATABASE_URL`). Idempotent:
already-empty `pdf_file` rows are skipped, so re-running is safe.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from crm.models import Act, Contract, Invoice, Quote

_MODELS = {"quote": Quote, "contract": Contract, "invoice": Invoice, "act": Act}


class Command(BaseCommand):
    help = "Clear cached document pdf_file so КП/договор/инвойс/акт re-render with the current template"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type", choices=["all", *_MODELS], default="all", help="Document type to invalidate (default: all)"
        )
        parser.add_argument("--id", type=int, default=None, help="Single document id (requires a concrete --type)")
        parser.add_argument("--since", default=None, help="Only documents created on/after this date (YYYY-MM-DD)")
        parser.add_argument("--sent-only", action="store_true", help="Quotes only: limit to SENT quotes (skip drafts)")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be cleared, change nothing")

    def handle(self, *args, **options):
        if options["id"] is not None and options["type"] == "all":
            raise CommandError("--id requires a concrete --type (quote/contract/invoice/act)")

        since = None
        if options["since"]:
            try:
                since = timezone.make_aware(datetime.strptime(options["since"], "%Y-%m-%d"))
            except ValueError as exc:
                raise CommandError(f"--since must be YYYY-MM-DD: {exc}")

        types = _MODELS if options["type"] == "all" else {options["type"]: _MODELS[options["type"]]}
        dry_run = options["dry_run"]
        grand_total = 0

        for name, model in types.items():
            queryset = model.objects.exclude(pdf_file="").exclude(pdf_file__isnull=True)
            if options["id"] is not None:
                queryset = queryset.filter(pk=options["id"])
            if since is not None:
                queryset = queryset.filter(created_at__gte=since)
            if options["sent_only"] and name == "quote":
                queryset = queryset.filter(status__code="SENT")

            cleared = 0
            for obj in queryset.iterator():
                if dry_run:
                    cleared += 1
                    continue
                try:
                    obj.pdf_file.delete(save=False)  # remove stored file + clear the field ref
                except OSError as exc:  # storage file already gone — still clear the DB pointer
                    self.stdout.write(self.style.WARNING(f"  {name} #{obj.pk}: storage delete failed ({exc})"))
                    obj.pdf_file = ""
                obj.save(update_fields=["pdf_file"])
                cleared += 1

            grand_total += cleared
            verb = "would clear" if dry_run else "cleared"
            self.stdout.write(f"{name}: {verb} {cleared} cached PDF(s)")

        style = self.style.WARNING if dry_run else self.style.SUCCESS
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(style(f"{prefix}Total: {grand_total} document PDF(s) invalidated"))
