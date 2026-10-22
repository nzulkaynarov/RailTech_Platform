"""`manage.py pairing_close_bootstrap` — закрыть окно первого сопряжения без кода (M3-ERP-05, ADR-0009).

Нужна на живых стендах, где шов CRM ↔ ERP уже настроен через `.env`: сопряжения в базе нет, `bootstrap_used_at` пуст,
и окно «без кода» открыто — его мог бы использовать любой, кто знает общий `PLATFORM_SSO_SECRET`. Команда ставит
постоянный флаг (идемпотентно); дальше сопрягаться можно только кодом из ERP, ключи обновляются «Обновить ключи».
Секретов не печатает и не принимает.
"""

from django.core.management.base import BaseCommand
from integration.services import pairing


class Command(BaseCommand):
    help = "Закрыть окно первого сопряжения без кода (идемпотентно; сопрягаться останется только кодом из ERP)."

    def handle(self, *args, **options):
        if pairing.bootstrap_is_open():
            pairing.close_bootstrap_window()
            self.stdout.write(
                "Окно первого сопряжения без кода закрыто. Сопрягать CRM — кодом из ERP (manage.py pairing_code)."
            )
        else:
            self.stdout.write("Окно первого сопряжения без кода уже закрыто — ничего не изменено.")
