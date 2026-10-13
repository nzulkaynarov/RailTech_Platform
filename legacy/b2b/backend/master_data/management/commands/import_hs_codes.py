"""Загрузка классификатора ТН ВЭД из файла.

Классификатор — публичные данные (код + наименование), но НЕ данные приложения: он приходит
редакциями извне, поэтому грузится management-командой, а не миграцией. Rule 1 не нарушен:
миграции сеют то, без чего код не работает; каталог ТН ВЭД — справочное наполнение, и система
обязана работать при пустом справочнике (тогда код вводится вручную, как сегодня).

Формат — CSV с колонками `code,name[,valid_from,valid_until]`; разделители внутри кода
(пробелы, точки) вычищаются. Иерархия проставляется автоматически по длине кода: 10 знаков
ищет родителя среди 8, затем 6, 4, 2.

    python manage.py import_hs_codes tnved.csv --source "ГТК РУз, редакция 2026"

Повторный запуск ОБНОВЛЯЕТ наименования и не плодит дубли (ключ — сам код), поэтому новую
редакцию можно накатывать поверх старой. Коды, которых нет в новом файле, НЕ удаляются:
выведенный из обращения код должен остаться, иначе перестанут читаться старые документы —
для этого есть `valid_until`.
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from master_data.models import HSCode
from master_data.tnved import link_hs_parents
from master_data.tnved import normalize_hs_code as normalize_code


class Command(BaseCommand):
    help = "Загрузить справочник ТН ВЭД из CSV (code,name[,valid_from,valid_until])."

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV-файл классификатора")
        parser.add_argument("--source", default="", help="Пометка редакции (например «ГТК РУз 2026»)")
        parser.add_argument("--delimiter", default=",", help="Разделитель CSV (по умолчанию запятая)")

    @transaction.atomic
    def handle(self, *args, **options):
        path = options["path"]
        created = updated = skipped = 0
        try:
            handle = open(path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"не удалось открыть {path}: {exc}") from exc

        with handle:
            for row in csv.DictReader(handle, delimiter=options["delimiter"]):
                code = normalize_code(row.get("code") or row.get("Код") or "")
                name = (row.get("name") or row.get("Наименование") or "").strip()
                if not code or not name or len(code) % 2:
                    skipped += 1
                    continue
                defaults = {
                    "name": name,
                    "level": len(code),
                    "source": options["source"],
                    "valid_from": row.get("valid_from") or None,
                    "valid_until": row.get("valid_until") or None,
                }
                _obj, was_created = HSCode.objects.update_or_create(code=code, defaults=defaults)
                created += int(was_created)
                updated += int(not was_created)

        linked = link_hs_parents()
        self.stdout.write(
            self.style.SUCCESS(
                f"ТН ВЭД: добавлено {created}, обновлено {updated}, пропущено {skipped}, "
                f"проставлено родителей {linked}"
            )
        )
