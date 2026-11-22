"""ДОК-13: пять образцов ERP и виды «Письмо», «Рапорт», «Произвольный» убраны из библиотеки шаблонов.

Факт, из которого выводится показ: образец виден, только если он активен; на образец, по которому выпущен документ,
миграция не бросает руку — снимает с показа. Вид без ссылок удаляется, вид со ссылками снимается с показа.
"""

import importlib

from django.apps import apps as django_apps

from core.seeds.documents import SAMPLE_TEMPLATES, TEMPLATE_KINDS
from crm import services as crm_services
from crm.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from crm.tests.test_document_templates import _api, _company, _member, lookups  # noqa: F401

MIGRATION = importlib.import_module("documents.migrations.0006_templates_cleanup")
RETIRED_SAMPLES = ["Гарантийное письмо", "Сопроводительное письмо", "Претензия", "Рапорт", "Доверенность"]


def _sample(name, kind_code):
    kind, _ = DocumentTemplateKind.objects.get_or_create(code=kind_code, defaults={"name": kind_code, "sort_order": 10})
    return DocumentTemplate.objects.create(company=None, name=name, kind=kind, is_sample=True, body_html="x")


def test_seed_no_longer_offers_retired_kinds_or_samples():
    assert {code for code, _name, _order in TEMPLATE_KINDS}.isdisjoint({"LETTER", "REPORT", "CUSTOM"})
    assert {name for name, _kind, _body in SAMPLE_TEMPLATES}.isdisjoint(RETIRED_SAMPLES)


def test_migration_deletes_unused_samples_and_hides_used_one(lookups):  # noqa: F811
    company = _company("Seller", "S1")
    free = _sample("Претензия", "LETTER")
    used = _sample("Гарантийное письмо", "LETTER")
    kept = _sample("Договор поставки (образец платформы)", "CONTRACT")
    GeneratedDocument.objects.create(
        company=company,
        template=used,
        number="DOC-1",
        status=GeneratedDocumentStatus.objects.get(code="ISSUED"),
    )

    MIGRATION.forward(django_apps, None)

    assert not DocumentTemplate.objects.filter(pk=free.pk).exists()
    used.refresh_from_db()
    assert used.is_active is False  # kept for the issued document, hidden
    assert DocumentTemplate.objects.get(pk=kept.pk).is_active is True
    # LETTER is still referenced by `used` -> hidden, not deleted; REPORT/CUSTOM have no templates -> deleted
    assert DocumentTemplateKind.objects.get(code="LETTER").is_active is False
    assert not DocumentTemplateKind.objects.filter(code__in=["REPORT", "CUSTOM"]).exists()


def test_migration_never_touches_company_templates(lookups):  # noqa: F811
    company = _company("Seller", "S1")
    user = _member(company, "o@t.uz")
    own = crm_services.create_template(company, user, name="Рапорт", kind_code="REPORT", body_html="x")

    MIGRATION.forward(django_apps, None)

    assert DocumentTemplate.objects.filter(pk=own.pk, is_active=True).exists()
    assert DocumentTemplateKind.objects.get(code="REPORT").is_active is False


def test_library_hides_deactivated_sample_but_shows_active_one(lookups):  # noqa: F811
    company = _company("Seller", "S1")
    user = _member(company, "o@t.uz")
    hidden = _sample("Гарантийное письмо", "LETTER")
    hidden.is_active = False
    hidden.save()
    shown = _sample("Акт приёма-передачи (образец платформы)", "ACT")

    ids = {row["id"] for row in _api(user).get("/api/v1/crm/document-templates/").json()}

    assert shown.id in ids
    assert hidden.id not in ids


def test_new_template_of_a_retired_kind_is_refused(lookups):  # noqa: F811
    company = _company("Seller", "S1")
    user = _member(company, "o@t.uz")
    MIGRATION.forward(django_apps, None)  # LETTER / REPORT / CUSTOM are gone or hidden

    for kind in ("LETTER", "REPORT", "CUSTOM", ""):
        resp = _api(user).post(
            "/api/v1/crm/document-templates/", {"name": "X", "kind": kind, "body_html": "<p>hi</p>"}, format="json"
        )
        assert resp.status_code == 400, kind
        assert resp.json() == {"detail": "TEMPLATE_KIND_INVALID"}, kind


def test_hidden_kind_with_existing_templates_refuses_new_ones(lookups):  # noqa: F811
    company = _company("Seller", "S1")
    user = _member(company, "o@t.uz")
    crm_services.create_template(company, user, name="Старый рапорт", kind_code="REPORT", body_html="x")
    MIGRATION.forward(django_apps, None)  # REPORT is referenced -> hidden, not deleted
    assert DocumentTemplateKind.objects.filter(code="REPORT", is_active=False).exists()

    resp = _api(user).post(
        "/api/v1/crm/document-templates/", {"name": "X", "kind": "REPORT", "body_html": "<p>hi</p>"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "TEMPLATE_KIND_INVALID"}
