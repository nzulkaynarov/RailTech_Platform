"""ТЕСТ-1: пометить компании «Тестовая» пачкой (решение владельца 2026-11-27, «Пометить как тестовые и скрыть»).

    python manage.py mark_test_companies --ids 12,15,40            # по умолчанию --dry-run: только числа, ничего не меняется
    python manage.py mark_test_companies --ids 12,15,40 --apply    # поставить отметку
    python manage.py mark_test_companies --ids 12,15 --unmark --apply  # снять отметку

Ничего не удаляется: отмеченные компании уходят из рабочих списков, счётчиков и отчётов и видны по фильтру «Тестовые».
Вывод — только числа (без названий и данных), действие пишется в журнал; повтор безопасен.
⚠ Прод-операция: перед `--apply` проверьте, что это нужная база.
"""

from django.core.management.base import BaseCommand, CommandError
from parties.models import Company


def parse_ids(raw) -> list[int]:
    ids: list[int] = []
    for chunk in raw:
        for part in str(chunk).replace(" ", ",").split(","):
            if not part:
                continue
            if not part.isdigit() or int(part) < 1:
                raise CommandError("--ids: only positive integers separated by commas or spaces")
            if int(part) not in ids:
                ids.append(int(part))
    if not ids:
        raise CommandError("--ids is required")
    return ids


class Command(BaseCommand):
    help = "Пометить компании по id как «Тестовая» (по умолчанию --dry-run, печатаются только числа)"

    def add_arguments(self, parser):
        parser.add_argument("--ids", nargs="+", required=True, help="id компаний: 12,15,40 или 12 15 40")
        parser.add_argument("--apply", action="store_true", help="записать (без флага — только подсчёт)")
        parser.add_argument("--unmark", action="store_true", help="снять отметку вместо постановки")

    def handle(self, *args, **options):
        from portal.desk.service_counterparty import set_test

        ids = parse_ids(options["ids"])
        wanted = not options["unmark"]
        found = {c.pk: c for c in Company.objects.filter(pk__in=ids)}
        missing = [pk for pk in ids if pk not in found]
        already = [pk for pk, company in found.items() if company.is_test == wanted]
        todo = [pk for pk in ids if pk in found and pk not in already]
        changed = 0
        if options["apply"]:
            for pk in todo:
                set_test(found[pk], wanted, actor=None)
                changed += 1
        mode = "apply" if options["apply"] else "dry-run"
        self.stdout.write(
            f"mark_test_companies [{mode}] {'mark' if wanted else 'unmark'}: requested={len(ids)} found={len(found)} "
            f"missing={len(missing)} already={len(already)} to_change={len(todo)} changed={changed}"
        )
        if not options["apply"] and todo:
            self.stdout.write("dry-run: nothing changed; repeat with --apply")
