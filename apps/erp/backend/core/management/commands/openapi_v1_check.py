"""`manage.py openapi_v1_check` — выгрузка OpenAPI `/api/v1` должна строиться без предупреждений drf-spectacular (D2-0).

Вызывается из `scripts/test_backend_local.sh --openapi` (то есть из `make -C apps/erp openapi` и `openapi-check`) и
повторена тестом `core/tests/test_openapi_v1_clean.py`. Подробности и границы проверки — `core/openapi.py`.
"""

from django.core.management.base import BaseCommand, CommandError

from core.openapi import check_v1_schema


class Command(BaseCommand):
    help = "Строит выгрузку /api/v1 и падает при любом предупреждении или ошибке drf-spectacular."

    def handle(self, *args, **options):
        problems = check_v1_schema()
        if problems:
            for problem in sorted(problems):
                self.stderr.write(f"  - {problem}")
            raise CommandError(
                f"Выгрузка /api/v1 с предупреждениями drf-spectacular ({len(problems)}): схема угадана или потеряна. "
                "Добавьте extend_schema / сериализатор запроса и ответа (CONVENTIONS ERP §5) и повторите."
            )
        self.stdout.write("Выгрузка /api/v1 без предупреждений drf-spectacular.")
