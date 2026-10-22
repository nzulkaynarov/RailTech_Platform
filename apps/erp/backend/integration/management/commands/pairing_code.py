"""`manage.py pairing_code` — одноразовый код сопряжения с CRM для первого запуска (M3-ERP-05).

Код печатается в stdout один раз и нигде не сохраняется открытым (в базе — хеш). В скрипты и логи CI его не пишем:
вводить его надо в CRM, «Подключения → ERP → Подключить ERP», в течение срока действия.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from integration.services import pairing


class Command(BaseCommand):
    help = "Выпустить одноразовый код сопряжения с CRM (15 минут по умолчанию, предыдущий неиспользованный гасится)."

    def handle(self, *args, **options):
        issued = pairing.issue_code(created_by=None)
        minutes = max(1, issued.ttl_seconds // 60)
        self.stdout.write(f"Код сопряжения: {issued.code}")
        self.stdout.write(
            f"Действует {minutes} мин (до {timezone.localtime(issued.expires_at):%Y-%m-%d %H:%M}), использовать можно один раз."
        )
        self.stdout.write("Введите его в CRM: Подключения → ERP → «Подключить ERP».")
