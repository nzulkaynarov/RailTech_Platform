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
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from master_data.models import HSCode

DIGITS = re.compile(r"\D+")


def normalize_code(raw: str) -> str:
    return DIGITS.sub("", raw or "")


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

        linked = self._link_parents()
        self.stdout.write(
            self.style.SUCCESS(
                f"ТН ВЭД: добавлено {created}, обновлено {updated}, пропущено {skipped}, "
                f"проставлено родителей {linked}"
            )
        )

    def _link_parents(self) -> int:
        """Иерархия выводится из самих кодов: у 10-значного родитель — ближайший более короткий."""
        by_code = dict(HSCode.objects.values_list("code", "id"))
        linked = 0
        for code, pk in by_code.items():
            parent_id = None
            for cut in range(len(code) - 2, 1, -2):
                parent_id = by_code.get(code[:cut])
                if parent_id:
                    break
            if parent_id and parent_id != pk:
                HSCode.objects.filter(pk=pk).update(parent_id=parent_id)
                linked += 1
        return linked
