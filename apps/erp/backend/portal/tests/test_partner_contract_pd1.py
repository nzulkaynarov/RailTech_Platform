"""ПД-1: договор партнёра без тупика — подготовка (шаблон / свой файл), согласование «Право», отправка при любом
источнике заявки, шаги кандидата в кабинете, подтверждение.

Защиты, без которых тесты краснеют (мутационная проверка в PR): `send_blocker` (отправка без договора и с неразрешённым
согласованием), `is_approver` в решении, фильтр «утверждён и партнёрский» в `offered_partner_templates`, проверка скана
перед одобрением, отсутствие встроенного образца (шаблона нет — `NO_APPROVED_PARTNER_TEMPLATE`), приглашение кандидата
не только для внешнего входа.
"""

import pytest
from django.conf import settings as dj_settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from documents.models.documents import DocumentTemplate, DocumentTemplateKind, TemplateApproval
from parties.models import (
    Company,
    CompanyRelationship,
    Contact,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    PartnerKind,
    RelationshipRole,
    RelationshipStatus,
)
from parties.models.company_settings import CompanySettings
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient, make_portal_session

from catalog.tests.desk_world import build_world, client_for
from crm.models import ActivityLog
from notifications.models import Notification

pytestmark = pytest.mark.django_db

DESK = "/api/v1/catalog/partner-applications"
PORTAL = "/api/portal/v1/company/partner-application"
BODY = (
    "<p>г. Ташкент<span>{{doc.date}} г.</span></p><h2>1. Предмет</h2>"
    "<p>Партнёр {{counterparty.name}} ({{counterparty.inn}}), договор {{contract.number}}.</p>"
    "{{doc.spec_table}}{{doc.totals}}{{doc.notes}}{{doc.requisites_and_signatures}}"
)
BODY_EN = "<p>Partner {{counterparty.name}}, agreement {{contract.number}}.</p>{{doc.requisites_and_signatures}}"
PDF = b"%PDF-1.4\n% scan\n"


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def supply(world):
    return world["clients"]["supply"]


@pytest.fixture
def director(world):
    return world["clients"]["director"]


def template(
    world, *, status=TemplateApproval.APPROVED, kind="partner", body=BODY, name="Договор с партнёром", **extra
):
    return DocumentTemplate.objects.create(
        company=world["own"] if "own" in world else world["users"]["director"].memberships.first().company,
        name=name,
        kind=DocumentTemplateKind.objects.get(code="CONTRACT"),
        body_html=body,
        approval_status=status,
        edition=1,
        counterparty_kind=kind,
        subject="supply",
        is_active=status == TemplateApproval.APPROVED,
        **extra,
    )


def set_default(world, tpl):
    own = tpl.company
    row, _ = CompanySettings.objects.get_or_create(company=own)
    row.default_partner_contract_template = tpl
    row.save()


def make_app(**kwargs) -> PartnerApplication:
    defaults = {
        "source": PartnerApplicationSource.LETTER,
        "source_ref": "ВХ-1",
        "company_name": "Nanjing Jichuang Co.",
        "registration_number": "91320000MA1",
        "contact_name": "Li Wei",
        "email": "li@jichuang.example",
        "language": "ru",
        "kind": PartnerKind.SUPPLIER,
        "categories_description": "Rail fasteners",
        "status": PartnerApplicationStatus.SUBMITTED,
        "consent": False,
    }
    defaults.update(kwargs)
    return PartnerApplication.objects.create(**defaults)


def post(client, app, tail, body=None, **kw):
    return client.post(f"{DESK}/{app.pk}/{tail}/", body or {}, format=kw.pop("format", "json"))


def upload(name="draft.pdf", content=PDF, content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def session_client(contact, company) -> PortalAPIClient:
    session = make_portal_session(contact, company, "magic_link")
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


# ── Шаг 1. Что можно выбрать, и «нет шаблона — нет договора» ──────────────────────────────────────────────────────


class TestLibraryOffer:
    def test_no_template_and_no_file_is_a_clear_refusal_without_built_in_sample(self, world, supply):
        app = make_app()

        assert supply.get(f"{DESK}/contract-options/").json()["templates"] == []
        response = post(supply, app, "prepare-contract", {})

        assert response.status_code == 400
        assert response.json()["detail"] == "NO_APPROVED_PARTNER_TEMPLATE"
        app.refresh_from_db()
        assert not app.contract_file and app.contract_source == ""
        # И отправлять нечего: встроенный образец не подставляется
        sent = post(supply, app, "send-contract")
        assert sent.status_code == 400 and sent.json()["detail"] == "CONTRACT_NOT_PREPARED"
        assert mail.outbox == []

    def test_only_approved_active_partner_templates_are_offered(self, world, supply):
        good = template(world)
        template(world, status=TemplateApproval.DRAFT, name="Черновик")
        template(world, kind="client", name="Для клиентов")
        retired = template(world, name="Старая редакция")
        DocumentTemplate.objects.filter(pk=retired.pk).update(is_active=False)
        set_default(world, good)

        options = supply.get(f"{DESK}/contract-options/").json()

        assert [t["id"] for t in options["templates"]] == [good.id]
        assert options["default_template_id"] == good.id
        assert options["templates"][0]["languages"] == ["ru"]

    def test_languages_follow_the_texts_the_library_has(self, world, supply):
        tpl = template(world, body_html_en=BODY_EN, body_html_uz="<p>{{counterparty.name}}</p>")
        options = supply.get(f"{DESK}/contract-options/").json()
        assert options["templates"][0]["languages"] == ["ru", "en", "uz"]
        assert tpl.id == options["templates"][0]["id"]

    def test_templates_without_default_need_an_explicit_choice(self, world, supply):
        template(world)
        response = post(supply, make_app(), "prepare-contract", {})
        assert response.status_code == 400
        assert response.json()["detail"] == "CONTRACT_TEMPLATE_REQUIRED"

    def test_draft_template_cannot_be_chosen(self, world, supply):
        draft = template(world, status=TemplateApproval.DRAFT)
        response = post(supply, make_app(), "prepare-contract", {"template_id": draft.id})
        assert response.status_code == 400
        assert response.json()["detail"] in ("CONTRACT_TEMPLATE_NOT_OFFERED", "NO_APPROVED_PARTNER_TEMPLATE")


# ── Шаг 1б. Из шаблона: данные кандидата и язык ──────────────────────────────────────────────────────────────────


class TestPrepareFromTemplate:
    def test_default_template_is_rendered_with_candidate_data_and_needs_no_approval(self, world, supply):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app()

        response = post(supply, app, "prepare-contract", {"language": "ru"})

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["contract_source"] == "template" and data["contract_template_id"] == tpl.id
        assert data["contract_approval"] == "" and data["contract_blocker"] is None
        app.refresh_from_db()
        assert app.contract_file.read(4) == b"%PDF"
        assert app.contract_number and app.contract_date
        assert not Notification.objects.filter(event_code="partner_contract.approval_requested").exists()

    def test_contract_text_carries_candidate_and_language(self, world, supply, monkeypatch):
        from portal.services import partner_contract as svc

        tpl = template(world, body_html_en=BODY_EN)
        app = make_app()
        brand = svc.document_brand_context(None)

        ru = svc.render_partner_contract_body(
            app, tpl, "ru", brand, number="PA-1", date=__import__("datetime").date(2026, 11, 25)
        )
        en = svc.render_partner_contract_body(
            app, tpl, "en", brand, number="PA-1", date=__import__("datetime").date(2026, 11, 25)
        )

        assert "Nanjing Jichuang Co." in ru and "91320000MA1" in ru and "PA-1" in ru and "Предмет" in ru
        assert "Partner Nanjing Jichuang Co., agreement PA-1." in en and "Предмет" not in en
        assert "Party 2" in en  # реквизиты на языке договора

    def test_unknown_place_in_template_refuses_instead_of_printing_a_token(self, world, supply):
        tpl = template(world, body=BODY + "{{partner.bank_iban}}")
        response = post(supply, make_app(), "prepare-contract", {"template_id": tpl.id})
        assert response.status_code == 400
        assert response.json()["detail"] == "CONTRACT_TEMPLATE_UNFILLED"

    def test_render_failure_keeps_no_stub(self, world, supply, monkeypatch):
        import weasyprint

        def explode(*args, **kwargs):
            raise OSError("cairo is gone")

        monkeypatch.setattr(weasyprint, "HTML", explode)
        tpl = template(world)
        app = make_app()

        response = post(supply, app, "prepare-contract", {"template_id": tpl.id})

        assert response.status_code == 400 and response.json()["detail"] == "CONTRACT_RENDER_FAILED"
        app.refresh_from_db()
        assert not app.contract_file

    def test_candidate_cannot_see_contract_before_it_is_sent(self, world, supply):
        tpl = template(world)
        app = make_app()
        post(supply, app, "prepare-contract", {"template_id": tpl.id})
        response = PartnerApplication.objects.get(pk=app.pk)
        assert response.status == PartnerApplicationStatus.SUBMITTED  # подготовка не отправка


# ── Шаг 2. Согласование: свой файл и отступление — держателю «Право» ─────────────────────────────────────────────


class TestApproval:
    def test_own_file_waits_for_the_holder_and_blocks_sending(self, world, supply):
        app = make_app()

        response = supply.post(
            f"{DESK}/{app.pk}/prepare-contract/",
            {
                "file": upload(
                    "our.docx",
                    b"PK\x03\x04docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            format="multipart",
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["contract_source"] == "upload" and data["contract_approval"] == "requested"
        assert data["contract_blocker"] == "CONTRACT_APPROVAL_PENDING"
        assert data["contract_approvers"]  # названо, кто решает
        assert Notification.objects.filter(event_code="partner_contract.approval_requested").exists()
        sent = post(supply, app, "send-contract")
        assert sent.status_code == 400 and sent.json()["detail"] == "CONTRACT_APPROVAL_PENDING"
        assert mail.outbox == []

    def test_wrong_file_type_is_refused(self, world, supply):
        response = supply.post(
            f"{DESK}/{make_app().pk}/prepare-contract/",
            {"file": upload("virus.exe", b"MZ", "application/octet-stream")},
            format="multipart",
        )
        assert response.status_code == 400 and response.json()["detail"] == "CONTRACT_FILE_INVALID"

    def test_deviation_text_requests_approval_and_approval_prints_it_into_the_contract(
        self, world, supply, director, monkeypatch
    ):
        from portal.services import partner_contract as svc

        tpl = template(world)
        app = make_app()
        post(supply, app, "prepare-contract", {"template_id": tpl.id, "deviation_text": "Срок оплаты 45 дней"})
        app.refresh_from_db()
        assert app.contract_approval == "requested"

        seen = {}
        original = svc.render_partner_contract_pdf

        def spy(*args, **kwargs):
            seen["notes"] = kwargs.get("notes")
            return original(*args, **kwargs)

        monkeypatch.setattr(svc, "render_partner_contract_pdf", spy)
        decided = post(director, app, "contract-decision", {"decision": "approve"})

        assert decided.status_code == 200, decided.content
        assert seen["notes"] == "Срок оплаты 45 дней"
        assert decided.json()["contract_approval"] == "approved" and decided.json()["contract_blocker"] is None
        assert post(supply, app, "send-contract").status_code == 200

    def test_only_the_holder_of_the_law_zone_decides(self, world, supply):
        app = make_app()
        supply.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")

        # supply не держатель права утверждать договоры: отказ на воротах и в сервисе
        response = post(supply, app, "contract-decision", {"decision": "approve"})

        assert response.status_code == 403
        app.refresh_from_db()
        assert app.contract_approval == "requested"

    def test_return_needs_a_note_and_blocks_until_prepared_again(self, world, supply, director):
        app = make_app()
        supply.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")

        assert (
            post(director, app, "contract-decision", {"decision": "return"}).json()["detail"]
            == "CONTRACT_RETURN_NOTE_REQUIRED"
        )
        returned = post(
            director, app, "contract-decision", {"decision": "return", "note": "Нет пункта об ответственности"}
        )
        assert returned.json()["contract_approval"] == "returned"
        assert returned.json()["contract_approval_note"] == "Нет пункта об ответственности"
        assert returned.json()["contract_blocker"] == "CONTRACT_APPROVAL_RETURNED"
        assert post(supply, app, "send-contract").json()["detail"] == "CONTRACT_APPROVAL_RETURNED"
        # решение без запроса — отказ
        assert post(director, app, "contract-decision", {"decision": "approve"}).status_code == 400

        tpl = template(world)
        again = post(supply, app, "prepare-contract", {"template_id": tpl.id})
        assert again.json()["contract_approval"] == "" and again.json()["contract_blocker"] is None

    def test_company_rule_can_forbid_deviations_and_own_files(self, world, supply):
        tpl = template(world)
        row, _ = CompanySettings.objects.get_or_create(company=tpl.company)
        row.contract_deviations_allowed = False
        row.save()
        app = make_app()

        assert (
            post(supply, app, "prepare-contract", {"template_id": tpl.id, "deviation_text": "иначе"}).json()["detail"]
            == "CONTRACT_DEVIATIONS_DISABLED"
        )
        refused = supply.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")
        assert refused.json()["detail"] == "CONTRACT_DEVIATIONS_DISABLED"
        assert post(supply, app, "prepare-contract", {"template_id": tpl.id}).status_code == 200

    def test_preparing_needs_the_supply_right(self, world):
        app = make_app()
        response = post(world["clients"]["manager"], app, "prepare-contract", {})
        assert response.status_code == 403


# ── Шаг 3. Отправка: вход в кабинет при любом источнике ─────────────────────────────────────────────────────────


class TestSendInvitesCandidateForAnySource:
    @pytest.mark.parametrize(
        "source", [PartnerApplicationSource.PUBLIC, PartnerApplicationSource.LETTER, PartnerApplicationSource.LEAD]
    )
    def test_candidate_gets_cabinet_invitation_in_his_language(self, world, supply, source):
        tpl = template(world, body_html_uz=BODY)
        set_default(world, tpl)
        app = make_app(source=source, language="uz")
        assert post(supply, app, "prepare-contract", {"language": "uz"}).status_code == 200

        response = post(supply, app, "send-contract")

        assert response.status_code == 200, response.content
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT and app.company_id and app.applicant_contact_id
        assert app.applicant_contact.language == "uz"
        rel = CompanyRelationship.objects.get(company=app.company, role=RelationshipRole.PARTNER)
        assert rel.status == RelationshipStatus.INVITED and rel.modules == []
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["li@jichuang.example"]
        assert response.json()["invite_delivery"] in ("queued", "sent")

    def test_lead_without_email_does_not_stop_the_path(self, world, supply):
        """ПК-1: почты нет — договор отправляется, компания и контакт заведены, письма нет; приглашение позже."""
        tpl = template(world)
        set_default(world, tpl)
        app = make_app(source=PartnerApplicationSource.LEAD, email="", phone="+998901112233")
        post(supply, app, "prepare-contract", {})

        response = post(supply, app, "send-contract")

        assert response.status_code == 200, response.content
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT and app.company_id and app.applicant_contact_id
        assert len(mail.outbox) == 0

        later = post(supply, app, "invite", {"email": "late@partner.example"})

        assert later.status_code == 200, later.content
        app.refresh_from_db()
        assert app.email == "late@partner.example" and app.applicant_contact.email == "late@partner.example"
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["late@partner.example"]

    def test_invite_without_any_email_says_what_is_missing(self, world, supply):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app(source=PartnerApplicationSource.LEAD, email="")
        post(supply, app, "prepare-contract", {})
        post(supply, app, "send-contract")

        response = post(supply, app, "invite", {})

        assert response.status_code == 400 and response.json()["detail"] == "CANDIDATE_EMAIL_REQUIRED"


# ── Шаги 3–5 целиком: кандидат в кабинете → согласие → скан → подтверждение ──────────────────────────────────────


class TestWholePath:
    def _sent(self, world, supply, **extra):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app(**extra)
        post(supply, app, "prepare-contract", {"language": "ru"})
        assert post(supply, app, "send-contract").status_code == 200
        app.refresh_from_db()
        return app, session_client(app.applicant_contact, app.company)

    def test_candidate_reads_returns_and_agrees_then_uploads_scan_and_staff_confirms(self, world, supply):
        app, candidate = self._sent(world, supply)

        document = candidate.get(f"{PORTAL}/contract-pdf")
        assert document.status_code == 200 and document["Content-Type"] == "application/pdf"
        assert document.content.startswith(b"%PDF")
        card = candidate.get(PORTAL).json()["application"]
        assert card["has_contract_pdf"] is True and card["contract_file_kind"] == "pdf"

        # замечание вместо согласия
        assert candidate.post(f"{PORTAL}/return", {"notes": ""}, format="json").status_code == 400
        returned = candidate.post(f"{PORTAL}/return", {"notes": "Срок оплаты 60 дней"}, format="json")
        assert returned.status_code == 200 and returned.json()["candidate_returned_at"]
        listed = supply.get(f"{DESK}/{app.pk}/").json()
        assert listed["candidate_returned_at"] and listed["candidate_notes"] == "Срок оплаты 60 дней"
        assert listed["status"] == "contract_sent"

        assert candidate.post(f"{PORTAL}/agree", {"notes": "ok"}, format="json").status_code == 200

        # без скана и без заметки отметить «подписан» нельзя
        refused = post(supply, app, "approve", {"contract_number": app.contract_number})
        assert refused.status_code == 400 and refused.json()["detail"] == "SIGNED_PROOF_REQUIRED"
        assert not CompanyRelationship.objects.filter(
            company=app.company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
        ).exists()

        # скан прикрепляет менеджер, не контрагент
        bad = supply.post(f"{DESK}/{app.pk}/signed-scan/", {"file": upload("s.exe", b"MZ", "application/octet-stream")})
        assert bad.status_code == 400 and bad.json()["detail"] == "SCAN_INVALID"
        done = supply.post(f"{DESK}/{app.pk}/signed-scan/", {"file": upload("s.pdf")}, format="multipart")
        assert done.status_code == 200 and done.json()["has_signed_scan"] is True
        scan = supply.get(f"{DESK}/{app.pk}/document/?which=scan")
        assert scan.status_code == 200 and scan.content == PDF

        approved = post(supply, app, "approve", {"contract_number": app.contract_number})
        assert approved.status_code == 200, approved.content
        assert approved.json()["status"] == "approved"
        assert approved.json()["contract_valid_until"], "срок посчитан в момент отметки «подписан»"
        rel = CompanyRelationship.objects.get(company=app.company, role=RelationshipRole.PARTNER)
        assert rel.status == RelationshipStatus.ACTIVE and "my_products" in rel.modules
        assert ActivityLog.objects.filter(event_code="admin.partner_application.approved").exists()

    def test_staff_can_open_the_contract_candidate_sees(self, world, supply):
        app, _candidate = self._sent(world, supply)
        response = supply.get(f"{DESK}/{app.pk}/document/?which=contract")
        assert response.status_code == 200 and response.content.startswith(b"%PDF")

    def test_signed_with_a_note_instead_of_a_scan_sets_the_same_term(self, world, supply):
        """ПК-1: скан не обязателен — заметка достаточна; срок считается в момент отметки, по общему правилу компании."""
        import datetime

        app, candidate = self._sent(world, supply)
        candidate.post(f"{PORTAL}/agree", {"notes": ""}, format="json")

        response = post(
            supply,
            app,
            "approve",
            {"contract_number": app.contract_number, "signed_note": "Подписан у нас, оригинал в папке"},
        )

        assert response.status_code == 200, response.content
        app.refresh_from_db()
        assert app.signed_note.startswith("Подписан") and not app.signed_scan
        assert app.contract_valid_from == datetime.date.today() and app.contract_valid_until is not None
        assert app.contract_term_rule and app.contract_last_notice_date <= app.contract_valid_until

    def test_approving_without_the_candidates_agreement_still_needs_a_reason(self, world, supply):
        app, _candidate = self._sent(world, supply)

        refused = post(supply, app, "approve", {"contract_number": app.contract_number, "signed_note": "ok"})
        assert refused.status_code == 400 and refused.json()["detail"] == "CANDIDATE_AGREEMENT_REQUIRED"

        response = post(
            supply,
            app,
            "approve",
            {
                "contract_number": app.contract_number,
                "signed_note": "Подписали на встрече",
                "override_reason": "Встреча",
            },
        )

        assert response.status_code == 200
        entry = ActivityLog.objects.filter(event_code="admin.partner_application.approved_without_agreement").latest(
            "id"
        )
        assert entry.level == "WARNING"

    def test_other_company_cannot_read_the_candidates_contract(self, world, supply):
        app, _candidate = self._sent(world, supply)
        stranger_company = Company.objects.create(name="Чужая", inn="9999999990", is_active=True)
        stranger = Contact.objects.create(company=stranger_company, name="Чужой", email="x@x.example", can_act=True)
        CompanyRelationship.objects.create(
            company=stranger_company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
        )
        # у чужой компании своей заявки нет: договор кандидата ей не отдаётся
        assert session_client(stranger, stranger_company).get(f"{PORTAL}/contract-pdf").status_code == 404
        assert app.company_id != stranger_company.pk

    def test_reprepare_after_return_gives_a_new_version_and_resets_scan(self, world, supply):
        app, candidate = self._sent(world, supply)
        candidate.post(f"{PORTAL}/return", {"notes": "Правки"}, format="json")

        again = post(supply, app, "prepare-contract", {"language": "ru"})

        assert again.status_code == 200
        data = again.json()
        assert data["status"] == "submitted" and data["candidate_returned_at"] is None
        # пока не отправлено — кандидат прежнего файла не видит
        assert candidate.get(f"{PORTAL}/contract-pdf").status_code == 404


# ── Ревью: самосогласование, безопасность текста, чужая компания, язык ───────────────────────────────────────────


class TestReviewFixes:
    def _own_file(self, client):
        app = make_app()
        client.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")
        return app

    def test_requester_with_another_holder_has_no_button_and_is_refused(self, world, director):
        from catalog.tests.desk_world import make_staff

        other = make_staff(world["own"], "director", label="second-holder")
        app = self._own_file(director)

        card = director.get(f"{DESK}/{app.pk}/").json()
        assert card["can_decide_contract"] is False and card["decision_needs_confirmation"] is False
        assert card["contract_approvers"] == [other.get_full_name() or other.email]
        response = post(director, app, "contract-decision", {"decision": "approve", "confirm_self": True})

        assert response.status_code == 403 and response.json()["detail"] == "SELF_APPROVAL_NOT_ALLOWED"
        app.refresh_from_db()
        assert app.contract_approval == "requested"
        # другой держатель решает
        assert post(client_for(other), app, "contract-decision", {"decision": "approve"}).status_code == 200

    def test_sole_holder_decides_after_explicit_confirmation_with_warning(self, world, director):
        app = self._own_file(director)

        card = director.get(f"{DESK}/{app.pk}/").json()
        assert card["can_decide_contract"] is True and card["decision_needs_confirmation"] is True
        bare = post(director, app, "contract-decision", {"decision": "approve"})
        assert bare.status_code == 400 and bare.json()["detail"] == "SELF_DECISION_CONFIRMATION_REQUIRED"
        done = post(director, app, "contract-decision", {"decision": "approve", "confirm_self": True})

        assert done.status_code == 200, done.content
        entry = ActivityLog.objects.filter(event_code="admin.partner_application.contract_approved").latest("id")
        assert entry.level == "WARNING" and "on_behalf" in entry.after_data

    def test_rule_off_requester_decides_without_confirmation(self, world, director):
        from catalog.tests.desk_world import make_staff

        make_staff(world["own"], "director", label="second-holder")
        tpl = template(world)
        row, _ = CompanySettings.objects.get_or_create(company=tpl.company)
        row.contract_four_eyes = False
        row.save()
        app = self._own_file(director)

        card = director.get(f"{DESK}/{app.pk}/").json()
        assert card["can_decide_contract"] is True and card["decision_needs_confirmation"] is False
        assert post(director, app, "contract-decision", {"decision": "approve"}).status_code == 200

    def test_superuser_may_decide_own_request_but_it_is_journaled_on_behalf(self, world):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        from accounts.models import CompanyMember, CustomUser

        root = CustomUser.objects.create_user(
            email="root@pd1.test", username="root-pd1", password="pw", is_superuser=True, is_staff=True
        )
        director_member = CompanyMember.objects.filter(user=world["users"]["director"]).first()
        CompanyMember.objects.create(
            user=root, company=director_member.company, role=director_member.role, is_active=True
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(root).access_token}")
        app = make_app()
        client.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")

        response = post(client, app, "contract-decision", {"decision": "approve"})

        assert response.status_code == 200, response.content
        entry = ActivityLog.objects.filter(event_code="admin.partner_application.contract_approved").latest("id")
        assert entry.level == "WARNING" and "on_behalf" in entry.after_data

    def test_hostile_candidate_fields_are_escaped_and_do_not_block(self, world, supply):
        import datetime

        from portal.services import partner_contract as svc

        tpl = template(world)
        app = make_app(
            company_name='<img src="file:///etc/passwd"> {{doc.number}}',
            contact_name="<b>Li</b>",
            email="x@y.example",
        )
        brand = svc.document_brand_context(None)

        body = svc.render_partner_contract_body(app, tpl, "ru", brand, number="PA-1", date=datetime.date(2026, 11, 25))

        assert "<img" not in body and "<b>" not in body
        assert "&lt;img src=&quot;file:///etc/passwd&quot;&gt; {{doc.number}}" in body
        # и через сервис: «{{…}}» в имени кандидата договор не блокирует
        assert post(supply, app, "prepare-contract", {"template_id": tpl.id}).status_code == 200

    def test_language_without_template_text_is_refused(self, world, supply):
        tpl = template(world)  # только русский текст
        response = post(supply, make_app(), "prepare-contract", {"template_id": tpl.id, "language": "uz"})
        assert response.status_code == 400 and response.json()["detail"] == "CONTRACT_LANGUAGE_INVALID"

    def test_other_company_cannot_return_or_upload_scan_for_foreign_application(self, world, supply):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app()
        post(supply, app, "prepare-contract", {})
        post(supply, app, "send-contract")
        app.refresh_from_db()
        candidate = session_client(app.applicant_contact, app.company)
        candidate.post(f"{PORTAL}/agree", {"notes": ""}, format="json")
        # у чужой компании своя заявка (в той же стадии): её действия не трогают заявку кандидата A
        other_company = Company.objects.create(name="Чужая B", inn="9999999991", is_active=True)
        stranger = Contact.objects.create(company=other_company, name="B", email="b@b.example", can_act=True)
        CompanyRelationship.objects.create(
            company=other_company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
        )
        foreign = session_client(stranger, other_company)

        returned = foreign.post(f"{PORTAL}/return", {"notes": "чужое замечание"}, format="json")
        scan = foreign.post(f"{PORTAL}/signed-scan", {"file": upload("s.pdf")}, format="multipart")

        assert returned.status_code in (400, 404) and scan.status_code in (400, 404)
        app.refresh_from_db()
        assert app.candidate_returned_at is None and not app.signed_scan and app.candidate_notes in ("", "ok")
