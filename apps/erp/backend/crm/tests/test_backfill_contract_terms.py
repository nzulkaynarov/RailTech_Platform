"""ПК-1: `backfill_contract_terms` — срок подписанным договорам без срока: dry-run по умолчанию, `--apply`, идемпотентность.

Защиты, без которых тесты краснеют (мутационная проверка в PR): пропуск договоров со сроком, режим dry-run по умолчанию,
дата подписания из журнала/подписей/создания.
"""

import datetime as dt
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from crm.constants import ContractStatusCode as S
from crm.models import ActivityLog, Contract
from crm.tests.projects_world import contract_in, pw  # noqa: F401

pytestmark = pytest.mark.django_db


SIGNED_ON_MARCH_10 = {
    "client_signed_at": timezone.make_aware(dt.datetime(2026, 3, 9, 12, 0)),
    "manager_signed_at": timezone.make_aware(dt.datetime(2026, 3, 10, 12, 0)),
}


def _run(*args) -> str:
    out = StringIO()
    call_command("backfill_contract_terms", *args, stdout=out)
    return out.getvalue()


def test_dry_run_is_default_and_changes_nothing(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED, **SIGNED_ON_MARCH_10)

    out = _run()

    assert contract.number in out and "2026-03-10" in out and "2026-12-31" in out
    contract.refresh_from_db()
    assert contract.valid_until is None and contract.term_rule == ""


def test_apply_computes_term_from_signing_date_and_is_idempotent(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED, **SIGNED_ON_MARCH_10)

    _run("--apply")

    contract.refresh_from_db()
    assert contract.valid_from == dt.date(2026, 3, 10) and contract.valid_until == dt.date(2026, 12, 31)
    assert contract.last_notice_date == dt.date(2026, 12, 1) and contract.term_rule
    assert ActivityLog.objects.filter(event_code="contract.term_set", entity_id=contract.pk).count() == 1

    assert "Нечего менять" in _run("--apply")
    assert ActivityLog.objects.filter(event_code="contract.term_set", entity_id=contract.pk).count() == 1


def test_signing_date_falls_back_to_creation_and_skips_unsigned_and_termed(pw):  # noqa: F811
    no_dates = contract_in(pw, S.SIGNED, client_signed_at=None, manager_signed_at=None)
    Contract.objects.filter(pk=no_dates.pk).update(created_at=timezone.make_aware(dt.datetime(2026, 1, 5, 9, 0)))
    unsigned = contract_in(pw, S.PENDING_MANAGER)
    termed = contract_in(pw, S.SIGNED, valid_until=dt.date(2027, 12, 31))

    _run("--apply")

    no_dates.refresh_from_db()
    unsigned.refresh_from_db()
    termed.refresh_from_db()
    assert no_dates.valid_from == dt.date(2026, 1, 5)
    assert unsigned.valid_until is None
    assert termed.valid_until == dt.date(2027, 12, 31) and termed.term_rule == ""
