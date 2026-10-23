"""Повтор доставок и обработки по журналу шины rt_bus (B3, runbook `docs/runbooks/rt-bus-erp.md`).

    manage.py bus_retry --list [--status dead] [--subscriber crm]   журнал доставок
    manage.py bus_retry --delivery 42                               повторить одну доставку (попытки с нуля)
    manage.py bus_retry --all-dead [--subscriber crm]               повторить все dead (по подписчику или все)
    manage.py bus_retry --inbox <event-id>                          повторить обработку входящего (failed/skipped)
    manage.py bus_retry --metrics                                   метрики шины (то же, что пишет Beat в журнал)

Типичный случай: подписчик лежал или его адрес был неверным (404/410 сразу в `dead`) — после исправления адреса
`--all-dead --subscriber crm`. Команда ничего не отправляет сама: доставку ведёт `rt_bus.pump` воркера.
"""

from django.core.management.base import BaseCommand, CommandError
from integration.bus import get_bus


class Command(BaseCommand):
    help = "Журнал шины rt_bus: повторить доставку, все dead подписчика или обработку входящего."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--list", action="store_true", help="показать журнал доставок")
        group.add_argument("--delivery", type=int, help="id доставки для повтора")
        group.add_argument("--all-dead", action="store_true", help="повторить все доставки в dead")
        group.add_argument("--inbox", help="event id входящего события для повторной обработки")
        group.add_argument("--metrics", action="store_true", help="показать метрики шины")
        parser.add_argument("--subscriber", help="имя подписчика (для --list и --all-dead)")
        parser.add_argument("--status", help="статус доставки (для --list): pending, in_flight, delivered, dead")
        parser.add_argument("--limit", type=int, default=50, help="сколько строк журнала показать")

    def handle(self, *args, **options):
        bus = get_bus()
        if options["list"]:
            rows = bus.list_deliveries(
                status=options["status"], subscriber=options["subscriber"], limit=options["limit"]
            )
            for row in rows:
                self.stdout.write(
                    f"{row.id}\t{row.status}\t{row.subscriber}\t{row.event_type}\tattempts={row.attempts}"
                    f"\tcode={row.last_status_code}\t{row.last_error or ''}"
                )
            self.stdout.write(f"Строк: {len(rows)}")
        elif options["delivery"] is not None:
            if not bus.retry_delivery(options["delivery"]):
                raise CommandError(f"Доставка {options['delivery']} не найдена или уже доставлена")
            self.stdout.write(self.style.SUCCESS(f"Доставка {options['delivery']} поставлена на повтор"))
        elif options["all_dead"]:
            count = bus.retry_all_dead(options["subscriber"])
            self.stdout.write(self.style.SUCCESS(f"Поставлено на повтор (dead): {count}"))
        elif options["inbox"]:
            if not bus.retry_inbox(options["inbox"]):
                raise CommandError(f"Входящее {options['inbox']} не найдено или не в failed/skipped")
            self.stdout.write(self.style.SUCCESS(f"Входящее {options['inbox']} поставлено на повторную обработку"))
        else:
            metrics = bus.metrics()
            self.stdout.write(str(metrics))
