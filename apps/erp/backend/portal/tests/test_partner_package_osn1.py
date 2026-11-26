# flake8: noqa: F811
"""ОСН-1: пакет базовых документов кандидата в партнёры — из утверждённых шаблонов ролей, одно принятие, одно окно
замечаний с названием документа, одна отметка «подписан» со сроком по каждому документу.

Защиты, без которых тесты краснеют (мутационная проверка в PR): `NO_APPROVED_BASE_TEMPLATE` в `prepare_contract`
(пакет не собирается без утверждённого шаблона роли) и `apply_to_package` в `approve_application` (срок документов пакета
считается в момент отметки; NDA хранит поля тайны).
"""

import datetime

import pytest
from django.core import mail
from documents.models.documents import TemplateApproval
from parties.models import PartnerApplicationDocument
from parties.models.company_settings import CompanySettings
from portal.tests.test_partner_contract_pd1 import (  # noqa: F401
    DESK,
    PDF,
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

        response = post(
            supply, app, "approve", {"contract_number": app.contract_number, "signed_note": "Оригинал у нас"}
        )

        assert response.status_code == 200, response.content
        partnership = app.package_documents.get(base_role="partnership")
        nda = app.package_documents.get(base_role="nda")
        assert partnership.valid_from == datetime.date.today() and partnership.valid_until is not None
        assert nda.valid_from == datetime.date.today() and nda.valid_until is None
        assert nda.confidentiality_years == 3, "NDA хранит свой срок тайны из шаблона"
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert {d["base_role"]: d["confidentiality_years"] for d in card["package"]}["nda"] == 3


class TestFromArchive:
    """«Уже подписано на бумаге»: сразу конечное состояние, настоящие даты, без Кабинета и уведомлений."""

    def _record(self, supply, app, **extra):
        body = {"signed_on": "2025-03-14", "contract_number": "ДП-2025/17", **extra}
        return supply.post(f"{DESK}/{app.pk}/from-archive/", body, format="multipart")

    def test_package_is_recorded_signed_with_real_dates_scans_and_no_mail(self, world, supply):
        both(world)
        app = make_app()
        before = Notification.objects.count()

        response = self._record(
            supply,
            app,
            signed_on_nda="2025-03-20",
            scan_partnership=upload("p.pdf"),
            scan_nda=upload("n.pdf"),
            note="Оригиналы в папке «Партнёры 2025»",
        )

        assert response.status_code == 200, response.content
        card = response.json()
        assert card["status"] == "approved" and card["from_archive"] is True
        assert card["contract_number"] == "ДП-2025/17" and card["contract_date"] == "2025-03-14"
        rows = {r.base_role: r for r in app.package_documents.all()}
        assert rows["partnership"].signed_on == datetime.date(2025, 3, 14)
        assert rows["nda"].signed_on == datetime.date(2025, 3, 20)
        assert all(r.from_archive and r.signed_scan for r in rows.values())
        # срок считается от настоящей даты подписи, а не от сегодняшнего дня
        assert rows["partnership"].valid_from == datetime.date(2025, 3, 14)
        assert rows["partnership"].valid_until == datetime.date(2025, 12, 31)
        assert rows["nda"].valid_from == datetime.date(2025, 3, 20) and rows["nda"].confidentiality_years == 3
        # ничего не ушло: ни писем, ни уведомлений; в Кабинете у кандидата документов пакета нет
        assert len(mail.outbox) == 0
        assert Notification.objects.count() == before
        app.refresh_from_db()
        assert app.from_archive and app.signed_scan and app.signed_note.startswith("Оригиналы")
        assert PartnerApplicationDocument.objects.filter(application=app, from_archive=True).count() == 2

    def test_a_refused_approval_changes_nothing(self, world, supply):
        """Одобрение отказало (приостановленный партнёр): пакет, номер, дата и скан остаются как были — ничего не записано."""
        from parties.models import Company, CompanyRelationship, RelationshipRole, RelationshipStatus

        both(world)
        app = prepared(supply)
        company = Company.objects.create(name="Партнёр", inn="7744444444", is_active=True)
        CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.SUSPENDED, modules=[]
        )
        app.company = company
        app.save()
        app.refresh_from_db()
        was = (app.contract_number, app.contract_date, app.status)
        package_before = sorted(app.package_documents.values_list("pk", "number", "from_archive"))

        response = self._record(supply, app, scan_partnership=upload("p.pdf"))

        assert response.status_code == 400 and response.json()["detail"] == "PARTNER_SUSPENDED"
        app.refresh_from_db()
        assert (app.contract_number, app.contract_date, app.status) == was
        assert not app.signed_scan and not app.from_archive
        assert sorted(app.package_documents.values_list("pk", "number", "from_archive")) == package_before

    def test_incomplete_data_is_fine_and_a_future_date_is_not(self, world, supply):
        both(world)
        app = make_app()
        future = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        bad = self._record(supply, app, signed_on=future)
        assert bad.status_code == 400 and bad.json()["detail"] == "SIGNED_ON_INVALID"
        app.refresh_from_db()
        assert app.status == "submitted" and not app.package_documents.exists()

        bad_scan = self._record(supply, app, scan_nda=upload("s.exe", b"MZ", "application/octet-stream"))
        assert bad_scan.status_code == 400 and bad_scan.json()["detail"] == "SCAN_INVALID"

        ok = self._record(supply, app)  # ни сканов, ни заметки: неполные данные допустимы
        assert ok.status_code == 200 and ok.json()["status"] == "approved"
        again = self._record(supply, app)
        assert again.status_code == 400 and again.json()["detail"] == "APPLICATION_ALREADY_DECIDED"

    def test_candidate_cabinet_shows_no_documents_of_an_archived_package(self, world, supply):
        both(world)
        app = make_app()
        assert self._record(supply, app, scan_partnership=upload("p.pdf")).status_code == 200
        app.refresh_from_db()
        candidate = session_client(app.applicant_contact, app.company)
        assert candidate.get(PORTAL).json()["application"]["documents"] == []

    def test_an_ordinary_approval_still_invites_the_candidate(self, world, supply):
        """Пара к тесту выше: письмо уходит только при обычном пути, не из архива."""
        both(world)
        app = make_app()
        post(supply, app, "prepare-contract", {"package": True})
        post(supply, app, "send-contract")
        mail.outbox.clear()
        app.refresh_from_db()
        response = post(
            supply,
            app,
            "approve",
            {"contract_number": app.contract_number, "signed_note": "ok", "override_reason": "по телефону"},
        )
        assert response.status_code == 200 and response.json()["from_archive"] is False

    def test_archived_document_opens_its_scan_and_says_when_there_is_nothing(self, world, supply):
        both(world)
        app = make_app()
        assert self._record(supply, app, scan_nda=upload("n.pdf")).status_code == 200
        card = supply.get(f"{DESK}/{app.pk}/").json()
        has_file = {d["base_role"]: d["has_file"] for d in card["package"]}
        assert has_file == {"partnership": False, "nda": True}
        nda = app.package_documents.get(base_role="nda")
        assert supply.get(f"{DESK}/{app.pk}/document/?which=contract&doc={nda.pk}").content == PDF
        none = app.package_documents.get(base_role="partnership")
        assert supply.get(f"{DESK}/{app.pk}/document/?which=contract&doc={none.pk}").status_code == 404


def test_preparing_again_keeps_the_candidates_reply_per_document(world, supply):
    """Кандидат вернул NDA своим файлом и замечанием; повторная подготовка пересобирает пакет,
    но ответ кандидата по роли не теряется."""
    app, candidate = sent(world, supply)
    nda = app.package_documents.get(base_role="nda")
    reply = candidate.post(
        f"{PORTAL}/return",
        {"notes": "Срок тайны 5 лет", "document": nda.pk, "file": upload("nda.docx", DOCX, DOCX_TYPE)},
        format="multipart",
    )
    assert reply.status_code == 200, reply.content
    app.refresh_from_db()
    old = app.package_documents.get(base_role="nda")
    assert old.candidate_file and old.candidate_remark == "Срок тайны 5 лет"
    kept_name = old.candidate_file.name

    again = post(supply, app, "prepare-contract", {"package": True, "language": "ru"})
    assert again.status_code == 200, again.content

    new = app.package_documents.get(base_role="nda")
    assert new.pk != old.pk
    assert new.candidate_file.name == kept_name and new.candidate_remark == "Срок тайны 5 лет"
    assert new.candidate_file.read() == DOCX
