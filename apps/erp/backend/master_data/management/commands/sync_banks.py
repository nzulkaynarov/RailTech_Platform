"""Ручной запуск загрузки кодов банков из файла ЦБ (Х-12) — тем же сервисом, что и ежемесячная задача Beat.

    python manage.py sync_banks                  # страница ЦБ из настройки CBU_BANKS_URL
    python manage.py sync_banks --from-file x.xlsx   # файл, скачанный и приложенный вручную
"""

from django.core.management.base import BaseCommand, CommandError

from master_data.cbu_banks import BankFileError, refresh_banks


class Command(BaseCommand):
    help = "Добавить новые коды банков и обновить названия из файла ЦБ РУз; ничего не удаляет."

    def add_arguments(self, parser):
        parser.add_argument("--from-file", default="", help="xlsx «Филиалы коммерческих банков» вместо скачивания")

    def handle(self, *args, **options):
        content = None
        if options["from_file"]:
            try:
                with open(options["from_file"], "rb") as saved:
                    content = saved.read()
            except OSError as exc:
                raise CommandError(f"не удалось прочитать {options['from_file']}: {exc}") from exc
        try:
            summary = refresh_banks(content)
        except BankFileError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(summary.text())
