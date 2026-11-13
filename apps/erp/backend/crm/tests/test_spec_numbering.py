"""B-WDOCS2-1 — номера документов ERP по SPEC-v3 §2.2 (W-6).

Умолчание: `КП-ГГГГ/NNN`, `ДОГ-ГГГГ/NNN`, `СЧ-ГГГГ/NNN`, `АКТ-ГГГГ/NNN`; где SPEC молчит — тот же стиль: квитанция `КВ`,
накладная `НАК`, документ по шаблону `ДОК`. Выданные номера не меняются, счётчик года продолжается, новый номер не совпадает
с выданным в прежнем виде; своя маска компании не тронута; поиск находит и прежний, и новый вид; миграция documents/0004
обратима."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone

from accounts.models import Company, CompanySettings, CustomUser
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    DocumentNumberingScheme,
    DocumentSequence,
    Quote,
    QuoteStatus,
)
from crm.services import billing, contracts
from crm.services.numbering import next_document_number, number_search_q, preview_scheme_numbers, set_company_scheme
from crm.services.pdf_storage import safe_file_name

pytestmark = pytest.mark.django_db

migration = importlib.import_module("documents.migrations.0004_spec_numbering_defaults")


def _company(name, inn, prefix=""):
    company = Company.objects.create(name=name, inn=inn)
    if prefix:
        CompanySettings.objects.create(company=company, doc_number_prefix=prefix)
    return company


def _mint(doc_type, label, company=None):
    with transaction.atomic():
        return next_document_number(doc_type, label, company=company)


# ── Новый номер каждого вида ────────────────────────────────────────────────────────


def test_every_kind_gets_the_spec_number():
    year = timezone.now().year
    with transaction.atomic():
        minted = {
            "KP": next_document_number("KP"),
            "CT": contracts._next_contract_number(),
            "INV": billing._next_invoice_number(),
            "ACT": billing._next_act_number(),
            "RCP": billing._next_receipt_number(),
            "DN": next_document_number("DN"),
            "DOC": next_document_number("DOC"),
        }
    assert minted == {
        "KP": f"QT-{year}/001",
        "CT": f"CT-{year}/001",
        "INV": f"INV-{year}/001",
        "ACT": f"ACT-{year}/001",
        "RCP": f"RCP-{year}/001",
        "DN": f"DN-{year}/001",
        "DOC": f"DOC-{year}/001",
    }


def test_company_prefix_keeps_its_place_and_own_counter():
    year = timezone.now().year
    acme = _company("ACME", "6200000001", prefix="ACME")
    assert _mint("CT", "CT", acme) == f"ACME-CT-{year}/001"
    assert _mint("CT", "CT") == f"CT-{year}/001"  # платформенный счётчик отдельный
    assert _mint("CT", "CT", acme) == f"ACME-CT-{year}/002"


def test_preview_shows_the_spec_sample():
    year = timezone.now().year
    rows = preview_scheme_numbers(
        None, pattern="{prefix}{type}-{YYYY}/{seq}", padding=3, reset_period="yearly", start_value=0, prefix=""
    )
    assert {row["type_code"]: row["number"] for row in rows} == {
        "KP": f"QT-{year}/001",
        "CT": f"CT-{year}/001",
        "INV": f"INV-{year}/001",
        "ACT": f"ACT-{year}/001",
        "DOC": f"DOC-{year}/001",
        "REQ": f"RQ-{year}-001",
        "PRJ": f"PRJ-{year}-001",
        "RCP": f"RCP-{year}/001",
        "DN": f"DN-{year}/001",
        "PO": f"PO-{year}-001",
        "SHP": f"SHP-{year}-001",
        "PART": f"PA-{year}-0001",
    }


def test_more_than_999_documents_widen_the_number():
    year = timezone.now().year
    DocumentSequence.objects.create(company=None, doc_type="INV", year=year, period=str(year), last_value=999)
    assert _mint("INV", "INV") == f"INV-{year}/1000"


# ── Счётчик продолжается, уникальность ──────────────────────────────────────────────


def _contract_world():
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})
    status = ContractStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})[0]
    company = Company.objects.create(name="Numbering LLC", inn="6200000099")
    user = CustomUser.objects.create_user(email="spec-num@example.com", username="spec-num", password="pw")
    deal = Deal.objects.create(title="N", company=company, client=user, stage=DealStage.objects.get(code="DRAFT"))
    return deal, status


def _contract(deal, status, number, version):
    quote = Quote.objects.create(deal=deal, version=version, status=QuoteStatus.objects.get(code="DRAFT"))
    return Contract.objects.create(deal=deal, quote=quote, number=number, status=status)


def test_counter_continues_and_never_repeats_an_issued_number():
    year = timezone.now().year
    deal, status = _contract_world()
    _contract(deal, status, f"CT-{year}-00042", 1)  # выдан до перехода
    DocumentSequence.objects.create(company=None, doc_type="CT", year=year, period=str(year), last_value=42)

    number = _mint("CT", "CT")

    assert number == f"CT-{year}/043"  # не с 001: счётчик года продолжается
    assert not Contract.objects.filter(number=number).exists()
    _contract(deal, status, number, 2)  # глобальная уникальность `number` выдерживает новый номер
    assert DocumentSequence.objects.get(company=None, doc_type="CT", period=str(year)).last_value == 43


def test_issued_numbers_are_not_rewritten():
    year = timezone.now().year
    deal, status = _contract_world()
    old = _contract(deal, status, f"CT-{year}-00007", 1)
    _mint("CT", "CT")
    old.refresh_from_db()
    assert old.number == f"CT-{year}-00007"


# ── Своя маска компании ─────────────────────────────────────────────────────────────


def test_company_with_own_mask_is_untouched():
    year = timezone.now().year
    acme = _company("ACME", "6200000002", prefix="ACME")
    set_company_scheme(acme, pattern="{prefix}{type}-{YYYY}-{seq}", padding=5, type_labels={"CT": "CT"})
    assert _mint("CT", "CT", acme) == f"ACME-CT-{year}-00001"


# ── Поиск: прежний и новый вид ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query, expected",
    [
        ("CT-2026-00007", {"CT-2026-00007"}),  # прежний вид как набран
        ("ДОГ-2026/008", {"ДОГ-2026/008"}),  # новый вид как набран
        ("ДОГ-2026/7", {"CT-2026-00007"}),  # новый вид находит прежний номер
        ("CT-2026-00008", {"ДОГ-2026/008"}),  # прежний вид находит новый номер
        ("дог 2026 8", {"ДОГ-2026/008"}),
        ("dog-2026-8", {"ДОГ-2026/008"}),
        ("2026/7", {"CT-2026-00007"}),
        ("ACME-ДОГ-2026/9", {"ACME-ДОГ-2026/009"}),
        ("ДОГ-2026/9", {"ACME-ДОГ-2026/009"}),
        ("2026", {"CT-2026-00007", "ДОГ-2026/008", "ACME-ДОГ-2026/009"}),
        ("СЧ-2026/7", set()),  # другой вид документа
    ],
)
def test_search_finds_both_forms(query, expected):
    deal, status = _contract_world()
    for version, number in enumerate(("CT-2026-00007", "ДОГ-2026/008", "ACME-ДОГ-2026/009"), start=1):
        _contract(deal, status, number, version)
    found = set(Contract.objects.filter(number_search_q("number", query)).values_list("number", flat=True))
    assert found == expected


# ── Миграция documents/0004 ─────────────────────────────────────────────────────────


def _scheme(company, pattern, padding, labels):
    return DocumentNumberingScheme.objects.create(company=company, pattern=pattern, padding=padding, type_labels=labels)


def test_migration_switches_untouched_defaults_and_back():
    platform = _scheme(None, migration.OLD_PATTERN, 5, dict(migration.OLD_LABELS))
    saved_as_is = _scheme(_company("Plain", "6200000003", prefix="PL"), migration.OLD_PATTERN, 5, {})
    own_mask = _scheme(
        _company("Own", "6200000004", prefix="OWN"), "{type}/{YYYY}/{seq}", 5, dict(migration.OLD_LABELS)
    )
    own_label = _scheme(
        _company("Lbl", "6200000005", prefix="LB"), migration.OLD_PATTERN, 5, {**migration.OLD_LABELS, "CT": "ДГ"}
    )

    migration.to_spec_defaults(django_apps, None)
    for row in (platform, saved_as_is, own_mask, own_label):
        row.refresh_from_db()
    assert (platform.pattern, platform.padding, platform.type_labels) == (
        "{prefix}{type}-{YYYY}/{seq}",
        3,
        {"KP": "КП", "CT": "ДОГ", "INV": "СЧ", "ACT": "АКТ", "DOC": "ДОК"},
    )
    assert (saved_as_is.pattern, saved_as_is.padding) == ("{prefix}{type}-{YYYY}/{seq}", 3)
    assert (own_mask.pattern, own_mask.type_labels["CT"]) == ("{type}/{YYYY}/{seq}", "CT")  # своя маска
    assert (own_label.pattern, own_label.type_labels["CT"]) == (migration.OLD_PATTERN, "ДГ")  # своё обозначение

    migration.to_legacy_defaults(django_apps, None)
    platform.refresh_from_db()
    own_label.refresh_from_db()
    assert (platform.pattern, platform.padding, platform.type_labels) == (
        migration.OLD_PATTERN,
        5,
        dict(migration.OLD_LABELS),
    )
    assert own_label.type_labels["CT"] == "ДГ"


def test_migration_keeps_counters():
    year = timezone.now().year
    DocumentSequence.objects.create(company=None, doc_type="KP", year=year, period=str(year), last_value=41)
    _scheme(None, migration.OLD_PATTERN, 5, dict(migration.OLD_LABELS))
    migration.to_spec_defaults(django_apps, None)
    assert _mint("KP", "КП") == f"КП-{year}/042"


# ── Имя файла ───────────────────────────────────────────────────────────────────────


def test_file_name_has_no_path_separator():
    assert safe_file_name("Contract_ДОГ-2026/104.pdf") == "Contract_ДОГ-2026-104.pdf"
