"""Smoke-test the AI заявка extractor on a real client file.

    python manage.py ai_extract_test /path/to/client_zayavka.xlsx

Prints the normalised items as JSON. Requires ANTHROPIC_API_KEY + AI_IMPORT_ENABLED.
Use it to verify extraction on real client formats before wiring the UI.
"""

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sourcing.services_ai import extract_request_items


class Command(BaseCommand):
    help = "Run the AI заявка extractor on a file and print the recognised items as JSON."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the client file (xlsx/csv/pdf/png/jpg/txt)")

    def handle(self, *args, **options):
        path = options["path"]
        if not os.path.exists(path):
            raise CommandError(f"File not found: {path}")
        if not settings.AI_IMPORT_ENABLED:
            raise CommandError("AI import disabled — set ANTHROPIC_API_KEY and AI_IMPORT_ENABLED=true")

        with open(path, "rb") as handle:
            content = handle.read()

        self.stdout.write(
            self.style.WARNING(f"Extracting from {os.path.basename(path)} via {settings.AI_IMPORT_MODEL} …")
        )
        items = extract_request_items(content, os.path.basename(path))
        self.stdout.write(self.style.SUCCESS(f"Recognised {len(items)} items:"))
        self.stdout.write(json.dumps(items, ensure_ascii=False, indent=2))
