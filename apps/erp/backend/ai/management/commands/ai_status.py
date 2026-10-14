"""`manage.py ai_status` — состояние ИИ ERP одним JSON без вызова моделей (§3.13, M3-ERP-06)."""

import json

from ai.services.status import ai_status
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Печатает состояние ИИ ERP: шлюз, бюджет и расход за сегодня, ошибки, алиасы, версии промптов."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(ai_status(), ensure_ascii=False, indent=2, default=str))
