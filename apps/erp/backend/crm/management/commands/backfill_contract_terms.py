"""ПК-1: дать срок подписанным договорам, у которых его нет (решение владельца 2026-11-25).

Срок — по текущему правилу компании (ДС-1), тот же расчёт, что при отметке «подписан» (`contract_term.compute_term`),
от даты подписания; даты подписания нет — от даты создания договора.

    python manage.py backfill_contract_terms            # по умолчанию --dry-run: только таблица, ничего не меняется
    python manage.py backfill_contract_terms --apply    # записать срок

⚠ Прод-операция: перед `--apply` проверьте, что это нужная база. Идемпотентна: договор со сроком пропускается, повторный
запуск ничего не меняет.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm.constants import ContractStatusCode
from crm.models import ActivityLog, Contract
from crm.services import contract_term


def signing_date(contract) -> tuple[dt.date, str]:
    """Дата подписания и откуда она взята: журнал отметки «подписан», подписи сторон, иначе создание договора."""
    marked = (
        ActivityLog.objects.filter(
            entity_type="contract", entity_id=contract.pk, event_code__in=["contract.scan_attached", "contract.signed"]
        )
        .order_by("-timestamp")
        .first()
    )
    if marked is not None:
        return timezone.localtime(marked.timestamp).date(), "журнал"
    signed_at = max((d for d in (contract.manager_signed_at, contract.client_signed_at) if d), default=None)
    if signed_at is not None:
        return timezone.localtime(signed_at).date(), "подписи"
    return timezone.localtime(contract.created_at).date(), "создание"


class Command(BaseCommand):
    help = "Дать срок подписанным договорам без срока по текущему правилу компании (по умолчанию --dry-run)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--dry-run", action="store_true", help="Только таблица (по умолчанию)")
        group.add_argument("--apply", action="store_true", help="Записать срок")

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        pending = (
            Contract.objects.filter(status__code=ContractStatusCode.SIGNED, valid_until__isnull=True, term_rule="")
            .select_related("deal__company", "template", "quote", "status")
            .order_by("pk")
        )
        rows = []
        for contract in pending:
            signed_on, source = signing_date(contract)
            rules, term = contract_term.compute_term(
                contract_term._seller(contract), contract.template, contract.deal.company, signed_on
            )
            rows.append((contract, signed_on, source, rules, term))
        if not rows:
            self.stdout.write("Нечего менять: у всех подписанных договоров срок уже есть.")
            return
        self.stdout.write(
            f"{'договор':<22}{'подписан':<12}{'откуда':<10}{'правило':<15}{'с':<12}{'до':<12}{'отказ до':<12}"
        )
        for contract, signed_on, source, rules, term in rows:
            self.stdout.write(
                f"{contract.number:<22}{signed_on!s:<12}{source:<10}{rules['rule']:<15}"
                f"{term.valid_from!s:<12}{term.valid_until or '—'!s:<12}{term.last_notice_date or '—'!s:<12}"
            )
        if not apply:
            self.stdout.write(f"\nПробный прогон (--dry-run): изменилось бы {len(rows)}. Запись — с --apply.")
            return
        changed = 0
        with transaction.atomic():
            for contract, signed_on, _source, _rules, _term in rows:
                locked = Contract.objects.select_for_update(of=("self",)).get(pk=contract.pk)
                if locked.valid_until is not None or locked.term_rule:
                    continue  # параллельный запуск уже дал срок
                contract_term.apply_at_signing(locked, signed_on=signed_on)
                changed += 1
        self.stdout.write(f"\nЗаписано: {changed}.")
