"""Ручной запуск синхронизации ТН ВЭД с tarif.customs.uz.

Тонкая обёртка над `master_data.tnved.sync_tnved_codes` — тем же сервисом, который гоняет
еженедельный Celery-beat. Нужна для первичного наполнения и для внеплановой сверки.

Живая выгрузка занимает ~30 минут (сервер отдаёт ~8 строк/сек). Если ответ /hscode-list
уже сохранён в файл, `--from-file` накатывает его тем же путём записи мгновенно:

    python manage.py sync_tnved                       # живая выгрузка с tarif.customs.uz
    python manage.py sync_tnved --from-file dump.json # сохранённый ответ ({"aaData": [...]} или [...])
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from master_data.tnved import sync_tnved_codes


class Command(BaseCommand):
    help = "Синхронизировать справочник ТН ВЭД с tarif.customs.uz (живая выгрузка ~30 минут)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-file",
            default="",
            help="Сохранённый JSON-ответ /hscode-list вместо живой выгрузки",
        )

    def handle(self, *args, **options):
        rows = None
        if options["from_file"]:
            try:
                with open(options["from_file"], encoding="utf-8") as saved:
                    payload = json.load(saved)
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"не удалось прочитать {options['from_file']}: {exc}") from exc
            rows = payload.get("aaData") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise CommandError('ожидался JSON вида {"aaData": [...]} или список строк')
        else:
            self.stdout.write("Живая выгрузка с tarif.customs.uz — это займёт ~30 минут…")

        try:
            summary = sync_tnved_codes(rows=rows)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "ТН ВЭД: получено {fetched}, добавлено {created}, обновлено {updated}, "
                "закрыто {closed}, пропущено {skipped}, проставлено родителей {linked}".format(**summary)
            )
        )
