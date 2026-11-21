"""One-off Latin renumbering of ERP numbers (СЦ-5). Dry-run by default; `--apply` writes in one transaction.

    python manage.py renumber_latin --emit-mapping > erp-mapping.json      # ERP's own numbers, {old: new}
    python manage.py renumber_latin global-mapping.json                    # dry-run: «table.column id: было → станет»
    python manage.py renumber_latin global-mapping.json --apply            # idempotent; re-run changes nothing
    cat global-mapping.json | python manage.py renumber_latin -            # mapping from stdin

The mapping is a flat JSON object `{"ВХ-001/26": "IN-001/26", "ЗВ-2026-001": "RQ-2026-001", ...}` assembled from the
`--emit-mapping` output of every system. ERP touches only its own tables (see `crm/services/latin_renumber.py`).
"""

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from crm.services import latin_renumber


class Command(BaseCommand):
    help = "Apply the {old: new} number mapping to ERP tables (dry-run unless --apply); --emit-mapping prints ERP's own"

    def add_arguments(self, parser):
        parser.add_argument("mapping", nargs="?", help="Path to the mapping JSON, or - for stdin")
        parser.add_argument("--apply", action="store_true", help="Write the changes (one transaction); default dry-run")
        parser.add_argument("--emit-mapping", action="store_true", help="Print the mapping of ERP's own issued numbers")

    def handle(self, *args, **options):
        if options["emit_mapping"]:
            self.stdout.write(json.dumps(latin_renumber.emit_mapping(), ensure_ascii=False, indent=2, sort_keys=True))
            return
        source = options["mapping"]
        if not source:
            raise CommandError("mapping file (or -) is required")
        try:
            raw = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
            mapping = json.loads(raw)
        except (OSError, ValueError) as error:
            raise CommandError(f"cannot read mapping: {error}") from error
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise CommandError("mapping must be a flat JSON object of strings {old: new}")
        changes = latin_renumber.apply(mapping) if options["apply"] else latin_renumber.plan(mapping)
        for change in changes:
            self.stdout.write(change.line())
        verb = "changed" if options["apply"] else "would change (dry-run, add --apply)"
        self.stdout.write(f"{len(changes)} field(s) {verb}")
