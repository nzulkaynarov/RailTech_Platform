# flake8: noqa: F811
"""ОСН-1: пакет базовых документов кандидата в партнёры — из утверждённых шаблонов ролей, одно принятие, одно окно
замечаний с названием документа, одна отметка «подписан» со сроком по каждому документу.

Защиты, без которых тесты краснеют (мутационная проверка в PR): `NO_APPROVED_BASE_TEMPLATE` в `prepare_contract`
(пакет не собирается без утверждённого шаблона роли) и `apply_to_package` в `approve_application` (срок документов пакета
считается в момент отметки; NDA хранит поля тайны).
"""

import datetime

import pytest
from documents.models.documents import TemplateApproval
from parties.models import PartnerApplicationDocument
from parties.models.company_settings import CompanySettings
from portal.tests.test_partner_contract_pd1 import (  # noqa: F401
    DESK,
    PORTAL,
    _locmem_mail,
    director,
    make_app,
    post,
    session_client,
    supply,
    template,
    upload,
    world,
)

from notifications.models import Notification

pytestmark = pytest.mark.django_db

DOCX = b"PK\x03\x04" + b"\x00" * 64
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def base(world, role, name, **extra):
    return template(world, name=name, base_role=role, **extra)


def both(world):
    return (
        base(world, "partnership", "Договор о партнёрстве"),
        base(world, "nda", "Соглашение о неразглашении", confidentiality_years=3),
    )


def prepared(supply, **extra):
    app = make_app(**extra)
    response = post(supply, app, "prepare-contract", {"package": True, "language": "ru"})
    assert response.status_code == 200, response.content
    return app


def sent(world, supply):
    both(world)
    app = prepared(supply)
    assert post(supply, app, "send-contract").status_code == 200
    app.refresh_from_db()
    return app, session_client(app.applicant_contact, app.company)


class TestPackageBuild:
    def test_options_name_the_missing_role_instead_of_a_dead_button(self, world, supply):
        base(world, "partnership", "Договор о партнёрстве")
        package = supply.get(f"{DESK}/contract-options/").json()["package"]
        assert package["ready"] is False
        by_role = {r["base_role"]: r for r in package["roles"]}
        assert by_role["partnership"]["template_id"] and by_role["partnership"]["name"] == "Договор о партнёрстве"
        assert by_role["nda"]["template_id"] is None and by_role["nda"]["role_name"] == "Соглашение о неразглашении"

    def test_package_is_not_built_without_an_approved_template_of_a_role(self, world, supply):
        base(world, "partnership", "Договор о партнёрстве")
        base(world, "nda", "NDA черновик", status=TemplateApproval.DRAFT)
        app = make_app()

        response = post(supply, app, "prepare-contract", {"package": True})

        assert response.status_code == 400 and response.json()["detail"] == "NO_APPROVED_BASE_TEMPLATE"
        app.refresh_from_db()
        assert app.contract_source == "" and not app.package_documents.exists()

    def test_package_has_one_document_per_role_of_the_company_setting(self, world, supply):
        partnership, nda = both(world)
        app = prepared(supply)
        app.refresh_from_db()

        rows = list(app.package_documents.all())
        assert [r.base_role for r in rows] == ["partnership", "nda"]
        assert [r.template_id for r in rows] == [partnership.id, nda.id]
        assert all(bytes(r.file.read()).startswith(b"%PDF") for r in rows)
        assert rows[0].number == app.contract_number and rows[1].number == f"{app.contract_number}/2"
        app.refresh_from_db()
        assert app.contract_file.read().startswith(b"%PDF") and app.contract_approval == ""
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert [d["base_role"] for d in card["package"]] == ["partnership", "nda"]
        assert card["contract_blocker"] is None, "базовые документы без отступлений согласования не требуют"

        row, _ = CompanySettings.objects.get_or_create(company=partnership.company)
        row.partner_base_roles = ["nda"]
        row.save()
        post(supply, app, "prepare-contract", {"package": True})
        assert [r.base_role for r in app.package_documents.all()] == ["nda"], "прежний пакет заменён"

    def test_package_takes_no_deviation_and_no_own_file(self, world, supply):
        both(world)
        app = make_app()
        deviation = post(supply, app, "prepare-contract", {"package": True, "deviation_text": "Иначе"})
        assert deviation.status_code == 400 and deviation.json()["detail"] == "PACKAGE_NO_DEVIATION"
        own = supply.post(
            f"{DESK}/{app.pk}/prepare-contract/", {"package": "true", "file": upload()}, format="multipart"
        )
        assert own.status_code == 400 and own.json()["detail"] == "PACKAGE_NO_DEVIATION"


class TestCandidateSeesOnePackage:
    def test_documents_are_visible_only_after_sending_and_open_one_by_one(self, world, supply):
        both(world)
        app = prepared(supply)
        post(supply, app, "send-contract")
        app.refresh_from_db()
        candidate = session_client(app.applicant_contact, app.company)

        card = candidate.get(PORTAL).json()["application"]
        assert [d["base_role"] for d in card["documents"]] == ["partnership", "nda"]
        for item in card["documents"]:
            opened = candidate.get(f"{PORTAL}/contract-pdf?doc={item['id']}")
            assert opened.status_code == 200 and opened.content.startswith(b"%PDF")
        assert candidate.get(f"{PORTAL}/contract-pdf?doc=999999").status_code == 404

    def test_one_agree_accepts_the_whole_package(self, world, supply):
        app, candidate = sent(world, supply)
        assert candidate.post(f"{PORTAL}/agree", {}, format="json").status_code == 200
        app.refresh_from_db()
        assert app.status == "candidate_agreed" and app.package_documents.count() == 2


class TestRemarksNameTheDocument:
    def test_remark_with_own_docx_replaces_only_the_named_document(self, world, supply):
        app, candidate = sent(world, supply)
        nda = app.package_documents.get(base_role="nda")
        before = app.package_documents.get(base_role="partnership").file.read()

        response = candidate.post(
            f"{PORTAL}/return",
            {"notes": "Срок тайны 5 лет", "document": nda.pk, "file": upload("nda.docx", DOCX, DOCX_TYPE)},
            format="multipart",
        )

        assert response.status_code == 200, response.content
        nda.refresh_from_db()
        assert nda.file.read() == DOCX and nda.candidate_file and nda.candidate_remark == "Срок тайны 5 лет"
        partnership = app.package_documents.get(base_role="partnership")
        assert partnership.file.read() == before and not partnership.candidate_remark
        app.refresh_from_db()
        assert app.contract_file.read() == before, "основной файл не тронут: замечание к другому документу"
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert card["contract_blocker"] == "CONTRACT_APPROVAL_PENDING"
        assert supply.get(f"{DESK}/{app.pk}/document/?which=candidate&doc={nda.pk}").content == DOCX
        note = Notification.objects.filter(event_code="partner_contract.remarks").first()
        assert note and "Соглашение о неразглашении" in note.message

    def test_a_file_without_a_named_document_is_refused_when_there_are_several(self, world, supply):
        app, candidate = sent(world, supply)
        response = candidate.post(
            f"{PORTAL}/return",
            {"notes": "Моя редакция", "file": upload("x.docx", DOCX, DOCX_TYPE)},
            format="multipart",
        )
        assert response.status_code == 400 and response.json()["detail"] == "RETURN_DOCUMENT_REQUIRED"

    def test_a_remark_for_another_applications_document_is_refused(self, world, supply):
        app, candidate = sent(world, supply)
        foreign = PartnerApplicationDocument.objects.create(
            application=make_app(company_name="Другая", email="d@d.example"),
            base_role="nda",
            title="Чужой",
            file="x.pdf",
        )
        response = candidate.post(f"{PORTAL}/return", {"notes": "x", "document": foreign.pk}, format="json")
        assert response.status_code == 400 and response.json()["detail"] == "RETURN_DOCUMENT_INVALID"


class TestSignedTerms:
    def test_marking_signed_computes_each_documents_term_at_that_moment(self, world, supply):
        app, candidate = sent(world, supply)
        candidate.post(f"{PORTAL}/agree", {}, format="json")

        response = post(supply, app, "approve", {"contract_number": app.contract_number, "signed_note": "Оригинал у нас"})

        assert response.status_code == 200, response.content
        partnership = app.package_documents.get(base_role="partnership")
        nda = app.package_documents.get(base_role="nda")
        assert partnership.valid_from == datetime.date.today() and partnership.valid_until is not None
        assert nda.valid_from == datetime.date.today() and nda.valid_until is None
        assert nda.confidentiality_years == 3, "NDA хранит свой срок тайны из шаблона"
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert {d["base_role"]: d["confidentiality_years"] for d in card["package"]}["nda"] == 3
