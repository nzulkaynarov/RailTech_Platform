"""ДОК-14: the sample document of «Шаблоны» and «Реквизиты и бланк» is made by the real generator.

«Образец совпадает с документом, который получит клиент»: the same renderer functions, the active template, the live
blank, the next number of the sequence (not taken) and the document language. The PDF engine is replaced by a recorder
where the test is about WHAT is passed to it; one test prints a real PDF per kind.
"""

from types import SimpleNamespace

import pytest
from django.utils import translation
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyDocumentProfile, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import DocumentSequence, DocumentTemplate, DocumentTemplateKind
from crm.services.documents import rt_documents, sample
from crm.services.numbering import next_document_number, set_company_scheme

pytestmark = pytest.mark.django_db


@pytest.fixture
def seller():
    for code, name in (("CONTRACT", "Договор"), ("INVOICE", "Счёт"), ("ACT", "Акт"), ("LETTER", "Письмо")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    company = Company.objects.create(name="ООО «Образец-Продавец»", inn="3000000011")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="own@sample.uz", username="own@sample.uz", password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    from accounts.services.roles import ensure_default_company_roles

    CompanyMember.objects.get(user=user, company=company).company_roles.add(
        ensure_default_company_roles(company)["HEAD"]
    )
    return company, user


@pytest.fixture
def engine(monkeypatch):
    """Replace the PDF engine of rt_docs with a recorder: the calls say what the generator was given."""
    calls = []

    def fake(body, **kwargs):
        calls.append(SimpleNamespace(body=body, language=translation.get_language(), **kwargs))
        return SimpleNamespace(pdf=b"%PDF-recorded")

    monkeypatch.setattr("rt_docs.pdf.render_pdf", fake)
    return calls


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── the same generator ────────────────────────────────────────────────────────────────────────────────


def test_every_kind_prints_a_real_pdf(seller):
    company, user = seller
    for kind in sample.SAMPLE_KINDS:
        assert sample.render_sample(company, user, kind=kind).pdf.startswith(b"%PDF"), kind


@pytest.mark.parametrize(
    ("kind", "function"), [("KP", "quote_pdf"), ("CT", "contract_pdf"), ("INV", "invoice_pdf"), ("ACT", "act_pdf")]
)
def test_sample_calls_the_function_that_prints_the_working_document(seller, monkeypatch, kind, function):
    company, user = seller
    seen = []
    monkeypatch.setattr(rt_documents, function, lambda *a, **k: seen.append(k) or b"%PDF-spy")
    assert sample.render_sample(company, user, kind=kind).pdf == b"%PDF-spy"
    assert len(seen) == 1


def test_letter_sample_uses_the_renderer_of_generated_documents(seller, monkeypatch):
    company, user = seller
    seen = []
    monkeypatch.setattr(
        "crm.services.generated_documents.generated_pdf_bytes",
        lambda document, company_, brand, *, is_draft: seen.append((document, brand)) or b"%PDF-spy",
    )
    assert sample.render_sample(company, user, kind="DOC").pdf == b"%PDF-spy"
    assert seen[0][0].number == sample.peek(company, "DOC")


def test_sample_prints_the_active_template_version_not_a_private_copy(seller, monkeypatch):
    company, user = seller
    DocumentTemplate.objects.create(
        company=company,
        kind=DocumentTemplateKind.objects.get(code="INVOICE"),
        name="Счёт компании",
        body_html="<p>Текст нашего счёта {{doc.number}}</p>",
        is_active=True,
    )
    seen = []
    monkeypatch.setattr(rt_documents, "invoice_pdf", lambda *a, **k: seen.append(k["body_html"]) or b"%PDF-spy")
    sample.render_sample(company, user, kind="INV")
    assert seen == ["<p>Текст нашего счёта {{doc.number}}</p>"]


def test_unsaved_editor_text_is_printed_and_unknown_codes_are_reported(seller, monkeypatch):
    company, user = seller
    seen = []
    monkeypatch.setattr(rt_documents, "contract_pdf", lambda *a, **k: seen.append(k["body_html"]) or b"%PDF-spy")
    result = sample.render_sample(
        company, user, kind="CT", body_html="<p>Черновик {{no.such.code}}</p><script>x()</script>{{doc.spec_table}}"
    )
    assert "<script>" not in seen[0] and "Черновик" in seen[0]
    assert result.warnings == ["no.such.code"]


def test_oversize_text_and_unknown_kind_are_refused(seller):
    company, user = seller
    with pytest.raises(sample.SampleError) as big:
        sample.render_sample(company, user, kind="CT", body_html="x" * 100_001)
    assert big.value.code == "TEMPLATE_BODY_TOO_LARGE"
    with pytest.raises(sample.SampleError):
        sample.render_sample(company, user, kind="EVIL")


# ── the number: the mask, not the sequence ────────────────────────────────────────────────────────────


def test_sample_number_is_the_next_one_and_the_sequence_is_not_consumed(seller, engine):
    company, user = seller
    set_company_scheme(company, type_labels={"INV": "BILL"})
    before = list(DocumentSequence.objects.values_list("doc_type", "last_value"))

    sample.render_sample(company, user, kind="INV")
    sample.render_sample(company, user, kind="INV")

    assert list(DocumentSequence.objects.values_list("doc_type", "last_value")) == before
    shown = engine[0].meta.number
    assert shown.startswith("BILL") or "BILL" in shown
    assert engine[1].meta.number == shown
    # the working document that is issued next gets exactly the number the sample showed
    assert next_document_number("INV", company=company) == shown


def test_sample_follows_the_counter_when_documents_were_issued(seller, engine):
    company, user = seller
    next_document_number("CT", company=company)
    next_document_number("CT", company=company)
    sample.render_sample(company, user, kind="CT")
    assert engine[0].meta.number == next_document_number("CT", company=company)


# ── the blank ────────────────────────────────────────────────────────────────────────────────────────


def test_sample_changes_when_the_blank_changes(seller, engine):
    company, user = seller
    CompanyDocumentProfile.objects.create(company=company, footer_text="Подвал до")
    sample.render_sample(company, user, kind="INV")
    CompanyDocumentProfile.objects.filter(company=company).update(footer_text="Подвал после")
    sample.render_sample(company, user, kind="INV")
    assert engine[0].letterhead.footer == ("Подвал до",)
    assert engine[1].letterhead.footer == ("Подвал после",)


def test_unsaved_blank_draft_is_printed_and_never_saved(seller, engine):
    company, user = seller
    sample.render_sample(
        company, user, kind="KP", overrides={"footer_text": "Только на экране", "accent_color": "#8b0000"}
    )
    assert engine[0].letterhead.footer == ("Только на экране",)
    assert engine[0].letterhead.accent == "#8b0000"
    assert not CompanyDocumentProfile.objects.filter(company=company).exists()


def test_cover_letter_of_the_draft_is_printed_in_the_quote(seller, engine):
    company, user = seller
    sample.render_sample(
        company,
        user,
        kind="KP",
        overrides={"show_cover_letter": True, "cover_letter_text": "Уважаемый {{buyer}}, благодарим."},
    )
    texts = str(engine[0].body)
    assert "Уважаемый ООО «Образец-Клиент», благодарим." in texts


def test_quote_terms_of_the_sample_follow_the_rule_of_the_working_quote(seller, monkeypatch):
    """«Место отгрузки»: the working КП reads the saved profile (its address wins over the card); the sample must too."""
    company, user = seller
    company.legal_address = "Адрес из карточки"
    company.save()
    CompanyDocumentProfile.objects.create(company=company, legal_address="Адрес из профиля")
    seen = {}
    monkeypatch.setattr(
        rt_documents, "quote_pdf", lambda quote, **k: seen.update(quote=quote, extras=k["extras"]) or b"%PDF"
    )
    sample.render_sample(company, user, kind="KP")

    from crm.services.documents import quote_document_extras

    working = quote_document_extras(seen["quote"], company)
    assert seen["extras"]["quote_terms"] == working["quote_terms"]
    assert {"label": "Место отгрузки", "value": "Адрес из профиля"} in seen["extras"]["quote_terms"]


# ── the language ─────────────────────────────────────────────────────────────────────────────────────


def test_sample_is_printed_in_the_requested_language(seller, engine):
    company, user = seller
    sample.render_sample(company, user, kind="INV", language="en")
    sample.render_sample(company, user, kind="INV", language="uz")
    sample.render_sample(company, user, kind="INV", language="xx")  # unknown → the platform language
    assert [call.language for call in engine][:2] == ["en", "uz"]
    assert engine[2].language == "ru"


# ── the endpoints ────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_cache(settings, monkeypatch):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from crm import tasks

    monkeypatch.setattr(tasks.render_document_sample, "delay", lambda *args: sample.run_sample(*args))


def test_queue_poll_and_download(seller, api_cache, engine):
    company, user = seller
    api = _api(user)
    created = api.post("/api/v1/crm/document-samples/", {"kind": "INV", "language": "en"}, format="json")
    assert created.status_code == 202, created.content
    sample_id = created.json()["id"]

    state = api.get(f"/api/v1/crm/document-samples/{sample_id}/")
    assert state.status_code == 200 and state.json()["status"] == "ready"

    pdf = api.get(f"/api/v1/crm/document-samples/{sample_id}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf.content == b"%PDF-recorded"


def test_template_kind_picks_the_generator_of_its_kind(seller, api_cache, monkeypatch):
    company, user = seller
    seen = []
    monkeypatch.setattr(rt_documents, "act_pdf", lambda *a, **k: seen.append("act") or b"%PDF-spy")
    resp = _api(user).post(
        "/api/v1/crm/document-samples/", {"template_kind": "ACT", "body_html": "<p>x</p>"}, format="json"
    )
    assert resp.status_code == 202
    assert seen == ["act"]


def test_failed_render_is_reported_as_a_code(seller, api_cache, monkeypatch):
    company, user = seller

    def boom(*args, **kwargs):
        raise RuntimeError("engine down")

    monkeypatch.setattr(rt_documents, "invoice_pdf", boom)
    api = _api(user)
    sample_id = api.post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").json()["id"]
    state = api.get(f"/api/v1/crm/document-samples/{sample_id}/").json()
    assert state["status"] == "failed" and state["failure_code"] == "SAMPLE_RENDER_FAILED"
    assert api.get(f"/api/v1/crm/document-samples/{sample_id}/pdf/").status_code == 404


def test_another_company_cannot_read_the_sample(seller, api_cache, engine):
    company, user = seller
    sample_id = _api(user).post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").json()["id"]
    other = Company.objects.create(name="Чужая", inn="3000000022")
    stranger = CustomUser.objects.create_user(email="x@other.uz", username="x@other.uz", password="x")
    CompanyMember.objects.create(
        user=stranger, company=other, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    from accounts.services.roles import ensure_default_company_roles

    CompanyMember.objects.get(user=stranger, company=other).company_roles.add(
        ensure_default_company_roles(other)["HEAD"]
    )
    # settings of another company are not his to edit: refused before the cache is asked
    assert _api(stranger).get(f"/api/v1/crm/document-samples/{sample_id}/").status_code == 403
    assert _api(stranger).get(f"/api/v1/crm/document-samples/{sample_id}/pdf/").status_code == 403


def test_oversize_text_is_refused_before_the_queue_and_the_draft_is_cleaned(seller, api_cache, monkeypatch):
    company, user = seller
    from crm import tasks
    from crm.services.generated_documents import MAX_TEMPLATE_BODY_CHARS

    queued = []
    monkeypatch.setattr(tasks.render_document_sample, "delay", lambda *args: queued.append(args))
    api = _api(user)
    big = api.post(
        "/api/v1/crm/document-samples/",
        {"kind": "CT", "body_html": "x" * (MAX_TEMPLATE_BODY_CHARS + 1)},
        format="json",
    )
    assert big.status_code == 400 and big.json() == {"detail": "TEMPLATE_BODY_TOO_LARGE"}
    assert queued == []

    ok = api.post(
        "/api/v1/crm/document-samples/",
        {"kind": "KP", "draft": {"footer_text": "ok", "evil": "y" * 9_000_000, "legal_name": "n" * 9000}},
        format="json",
    )
    assert ok.status_code == 202
    sent = queued[0][3]["draft"]
    assert set(sent) == {"footer_text", "legal_name"}
    assert len(sent["legal_name"]) <= CompanyDocumentProfile._meta.get_field("legal_name").max_length


def _member_without_settings(company):
    from accounts.services.roles import ensure_default_company_roles

    viewer = CustomUser.objects.create_user(email="v@sample.uz", username="v@sample.uz", password="x")
    CompanyMember.objects.create(
        user=viewer, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    CompanyMember.objects.get(user=viewer, company=company).company_roles.add(
        ensure_default_company_roles(company)["VIEWER"]
    )
    return viewer


def test_without_settings_edit_every_action_is_403(seller, api_cache, engine):
    company, user = seller
    sample_id = _api(user).post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").json()["id"]
    viewer = _member_without_settings(company)
    api = _api(viewer)
    assert api.post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").status_code == 403
    assert api.get(f"/api/v1/crm/document-samples/{sample_id}/").status_code == 403
    assert api.get(f"/api/v1/crm/document-samples/{sample_id}/pdf/").status_code == 403


def test_a_sample_is_visible_only_to_who_asked_for_it(seller, api_cache, engine):
    company, user = seller
    sample_id = _api(user).post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").json()["id"]
    colleague = CustomUser.objects.create_user(email="c@sample.uz", username="c@sample.uz", password="x")
    CompanyMember.objects.create(
        user=colleague, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    from accounts.services.roles import ensure_default_company_roles

    CompanyMember.objects.get(user=colleague, company=company).company_roles.add(
        ensure_default_company_roles(company)["HEAD"]
    )
    assert _api(colleague).get(f"/api/v1/crm/document-samples/{sample_id}/").status_code == 404


def test_endpoints_refuse_bad_requests_and_anonymous(seller, api_cache):
    company, user = seller
    api = _api(user)
    assert api.post("/api/v1/crm/document-samples/", {"kind": "EVIL"}, format="json").status_code == 400
    assert api.post("/api/v1/crm/document-samples/", {"kind": ["INV"]}, format="json").status_code == 400
    assert api.get("/api/v1/crm/document-samples/" + "0" * 32 + "/").status_code == 404
    assert APIClient().post("/api/v1/crm/document-samples/", {"kind": "INV"}, format="json").status_code == 401


def _partnership_template(company):
    return DocumentTemplate.objects.create(
        company=company,
        name="Договор о партнёрстве",
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        body_html="<p>1. Стороны сотрудничают.</p>{{doc.requisites_and_signatures}}",
        counterparty_kind="partner",
        subject="",
    )


def test_sample_of_a_base_document_has_its_own_title_and_sides_without_supply_words(seller, engine):
    """ПК-1: образец «Договора о партнёрстве» не называется «Договором поставки» и не ссылается на КП."""
    company, user = seller
    template = _partnership_template(company)
    sample.render_sample(company, user, kind="CT", body_html=template.body_html, template=template)
    call = engine[0]
    assert call.meta.title == "Договор о партнёрстве" or call.meta.kind_label == "Договор о партнёрстве"
    assert all(row.label != "Основание" for row in (call.meta.info or ()))
    text = repr(call.body)
    assert "Поставщик" not in text and "Покупател" not in text
    assert "Компания" in text and "Партнёр" in text


def test_sample_of_a_supply_template_keeps_supply_frame_and_quote(seller, engine):
    company, user = seller
    template = _partnership_template(company)
    template.subject = "supply"
    template.counterparty_kind = "client"
    template.name = "Договор поставки"
    sample.render_sample(company, user, kind="CT", template=template)
    call = engine[0]
    assert "Поставщик" in repr(call.body)
    assert any(row.label == "Основание" for row in (call.meta.info or ()))
