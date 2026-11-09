"""Заявка партнёра: привязка и шлюз (FX-1, волна 19; правило PART-CRM — DECISIONS 2026-11-04).

Каждый класс — пункт аудита из `docs/runbooks/wave19-audit-fixes.md`:
(а) совпадение с существующей компанией — предложение человеку, не автопривязка;
(б) запасной поиск заявки по e-mail без проверки компании;
(в) одобрение без согласия кандидата и подпись договора сотрудником без полномочий;
(г) отклонённый кандидат не становится активным при первом входе;
(д) исход приглашения виден сотруднику;
(е) одобрение не снимает приостановку, не перезаписывает модули и сохранённую дату;
(ж) сбой рендера договора не сохраняет заглушку;
(з) ИНН длиннее поля компании;
(и) кандидат с отношением без модулей работает со своей заявкой.
"""

import pytest
from django.conf import settings as dj_settings
from django.core import mail
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
from portal.services.access import activate_on_first_login, company_has_cabinet_access
from portal.services.partner_contract import (
    PartnerContractRenderError,
    build_partner_contract_context,
    render_partner_contract_pdf,
)
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient, break_mail_handoff, make_portal_session

from catalog.tests.desk_world import build_world
from core.models.notifications import EmailLog
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

DESK = "/api/v1/catalog/partner-applications"
PORTAL = "/api/portal/v1/company/partner-application"
PUBLIC = "/api/portal/v1/auth/partner-application"


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
def victim():
    """Существующая компания, чей ИНН кандидат указал в анкете."""
    return Company.objects.create(name="ООО Настоящий Владелец", inn="7700000001", is_active=True)


def make_app(**kwargs) -> PartnerApplication:
    defaults = {
        "source": PartnerApplicationSource.PUBLIC,
        "company_name": "ООО Заявитель",
        "inn": "7711111111",
        "contact_name": "Кандидат Тестовый",
        "email": "candidate@applicant.example",
        "phone": "+998900000000",
        "language": "ru",
        "kind": PartnerKind.SUPPLIER,
        "categories_description": "Крепёж и рельсовые скрепления",
        "status": PartnerApplicationStatus.SUBMITTED,
    }
    defaults.update(kwargs)
    return PartnerApplication.objects.create(**defaults)


def agreed_app(company, **kwargs) -> PartnerApplication:
    """Заявка, по которой кандидат согласовал договор."""
    from django.utils import timezone

    return make_app(
        company=company,
        company_name=company.name,
        inn=company.inn or "",
        status=PartnerApplicationStatus.CANDIDATE_AGREED,
        candidate_agreed_at=timezone.now(),
        **kwargs,
    )


def session_client(contact, company) -> PortalAPIClient:
    session = make_portal_session(contact, company, "magic_link")
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


def candidate_session():
    """Новый кандидат: компания без типа клиента, отношение `invited` без модулей — как после отправки договора."""
    company = Company.objects.create(name="ООО Кандидат", inn="7722222222", is_active=True)
    contact = Contact.objects.create(company=company, name="Кандидат", email="c@candidate.example", can_act=True)
    CompanyRelationship.objects.create(
        company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
    )
    return company, contact, session_client(contact, company)


def post(client, app, tail, body=None):
    return client.post(f"{DESK}/{app.pk}/{tail}/", body or {}, format="json")


class TestCompanyMatchIsAProposal:
    """(а) ИНН анкеты не проверен: совпадение — вопрос сотруднику, до ответа ни контакта, ни входа."""

    def test_send_contract_does_not_bind_or_invite_without_confirmation(self, supply, victim):
        app = make_app(inn=victim.inn, email="attacker@evil.example")

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MATCH_CONFIRMATION_REQUIRED"
        app.refresh_from_db()
        assert app.company_id is None and app.status == PartnerApplicationStatus.SUBMITTED
        assert not Contact.objects.filter(company=victim).exists()
        assert not CompanyRelationship.objects.filter(company=victim).exists()
        assert mail.outbox == []

    def test_registration_number_match_is_a_proposal_too(self, supply):
        foreign = Company.objects.create(name="Foreign Ltd", registration_number="HRB-1", is_active=True)
        app = make_app(inn="", registration_number="hrb-1", email="attacker@evil.example")

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MATCH_CONFIRMATION_REQUIRED"
        assert not Contact.objects.filter(company=foreign).exists()

    def test_second_key_is_checked_when_the_first_one_finds_nothing(self, supply):
        foreign = Company.objects.create(name="Foreign Ltd", registration_number="HRB-2", is_active=True)
        app = make_app(inn="7799999999", registration_number="HRB-2", email="attacker@evil.example")

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MATCH_CONFIRMATION_REQUIRED"
        assert not Contact.objects.filter(company=foreign).exists()

    def test_approve_does_not_bind_without_confirmation(self, supply, victim):
        app = make_app(inn=victim.inn, email="attacker@evil.example", status=PartnerApplicationStatus.CONTRACT_SENT)

        response = post(supply, app, "approve", {"contract_number": "D-1", "override_reason": "бумажный договор"})

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MATCH_CONFIRMATION_REQUIRED"
        assert not Contact.objects.filter(company=victim).exists()
        assert not CompanyRelationship.objects.filter(company=victim).exists()

    def test_read_shows_what_has_to_be_confirmed(self, supply, victim):
        app = make_app(inn=victim.inn)

        data = supply.get(f"{DESK}/{app.pk}/").json()

        assert data["company_match_pending"] == "inn"
        assert data["matching_company_id"] == victim.pk

    def test_staff_confirmation_binds_and_invites(self, supply, victim):
        app = make_app(inn=victim.inn, email="owner@victim.example")

        response = post(supply, app, "send-contract", {"company_id": victim.pk})

        assert response.status_code == 200
        assert response.json()["company_match_pending"] is None
        app.refresh_from_db()
        assert app.company_id == victim.pk
        assert Contact.objects.filter(company=victim, email="owner@victim.example").exists()
        assert len(mail.outbox) == 1

    def test_new_company_is_refused_for_taken_inn(self, supply, victim):
        app = make_app(inn=victim.inn, email="attacker@evil.example")

        response = post(supply, app, "send-contract", {"create_new_company": True})

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_INN_TAKEN"
        assert Company.objects.filter(inn=victim.inn).count() == 1

    def test_new_company_allowed_for_registration_number_match(self, supply):
        foreign = Company.objects.create(name="Foreign Ltd", registration_number="HRB-3", is_active=True)
        app = make_app(inn="", registration_number="HRB-3", email="other@firm.example")

        response = post(supply, app, "send-contract", {"create_new_company": True})

        assert response.status_code == 200
        app.refresh_from_db()
        assert app.company_id not in (None, foreign.pk)
        assert not Contact.objects.filter(company=foreign).exists()

    def test_application_without_match_goes_as_before(self, supply):
        app = make_app()

        response = post(supply, app, "send-contract")

        assert response.status_code == 200
        assert response.json()["company_match_pending"] is None
        assert len(mail.outbox) == 1


class TestApplicationIsScopedToCompany:
    """(б) Контакт компании A с тем же адресом, что у заявки компании B, её не видит и не согласует."""

    @pytest.fixture
    def foreign_app(self, other_company, client_contact):
        return make_app(
            company=other_company,
            company_name=other_company.name,
            inn=other_company.inn or "",
            email=client_contact.email,
            status=PartnerApplicationStatus.CONTRACT_SENT,
            contract_number="B-1",
        )

    def test_status_does_not_show_foreign_application(self, portal_client, foreign_app):
        body = portal_client.get(PORTAL).json()
        assert body["application"] is None and body["has_application"] is False

    def test_contract_pdf_is_not_given_out(self, portal_client, foreign_app):
        assert portal_client.get(f"{PORTAL}/contract-pdf").status_code == 404

    def test_foreign_application_cannot_be_agreed(self, portal_client, foreign_app):
        response = portal_client.post(f"{PORTAL}/agree", {"notes": ""}, format="json")

        assert response.status_code == 400
        assert response.json()["detail"] == "NOT_IN_CONTRACT_SENT_STATUS"
        foreign_app.refresh_from_db()
        assert foreign_app.status == PartnerApplicationStatus.CONTRACT_SENT
        assert foreign_app.candidate_agreed_at is None

    def test_unbound_application_with_same_email_is_not_shown(self, portal_client, client_contact):
        make_app(email=client_contact.email)
        assert portal_client.get(PORTAL).json()["application"] is None


class TestApproveGate:
    """(в) Одобрение — только после согласия кандидата; обход — явный, с причиной в журнале."""

    @pytest.mark.parametrize("status_", [PartnerApplicationStatus.SUBMITTED, PartnerApplicationStatus.CONTRACT_SENT])
    def test_approve_without_agreement_is_refused(self, supply, status_):
        app = make_app(status=status_)

        response = post(supply, app, "approve", {"contract_number": "D-1"})

        assert response.status_code == 400
        assert response.json()["detail"] == "CANDIDATE_AGREEMENT_REQUIRED"
        app.refresh_from_db()
        assert app.status == status_
        assert not Company.objects.filter(inn=app.inn).exists()

    def test_blank_override_reason_is_not_an_override(self, supply):
        app = make_app()

        response = post(supply, app, "approve", {"contract_number": "D-1", "override_reason": "   "})

        assert response.status_code == 400
        assert response.json()["detail"] == "CANDIDATE_AGREEMENT_REQUIRED"

    def test_override_goes_to_the_journal_with_reason(self, world, supply):
        app = make_app(status=PartnerApplicationStatus.CONTRACT_SENT)

        response = post(
            supply, app, "approve", {"contract_number": "D-1", "override_reason": "договор подписан на бумаге"}
        )

        assert response.status_code == 200
        entry = ActivityLog.objects.get(
            entity_type="partner_application",
            entity_id=app.pk,
            event_code="admin.partner_application.approved_without_agreement",
        )
        assert entry.after_data["override_reason"] == "договор подписан на бумаге"
        assert entry.user_id == world["users"]["supply"].pk

    def test_override_is_refused_until_the_contract_is_sent(self, supply):
        app = make_app()

        response = post(supply, app, "approve", {"contract_number": "D-1", "override_reason": "договор на бумаге"})

        assert response.status_code == 400
        assert response.json()["detail"] == "CANDIDATE_AGREEMENT_REQUIRED"
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.SUBMITTED

    def test_agreed_application_is_approved_without_override(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7733333333", is_active=True)
        app = agreed_app(company)

        response = post(supply, app, "approve", {"contract_number": "D-1"})

        assert response.status_code == 200
        assert not ActivityLog.objects.filter(
            event_code="admin.partner_application.approved_without_agreement"
        ).exists()

    def test_override_does_not_print_candidate_agreement(self, supply):
        app = make_app(status=PartnerApplicationStatus.CONTRACT_SENT)
        post(supply, app, "approve", {"contract_number": "D-1", "override_reason": "договор подписан на бумаге"})
        app.refresh_from_db()

        context = build_partner_contract_context(app, draft=False)

        assert context["candidate_agreed"] is False

    def test_supply_employee_is_not_printed_as_signatory(self, world):
        app = make_app(status=PartnerApplicationStatus.APPROVED, reviewed_by=world["users"]["supply"])

        context = build_partner_contract_context(app, draft=False, director_user=world["users"]["supply"])

        assert context["signed_by_director"] is False
        assert world["users"]["supply"].email not in str(context["director_email"])

    def test_authorized_signatory_is_printed(self, world):
        director = world["users"]["director"]
        app = make_app(status=PartnerApplicationStatus.APPROVED, reviewed_by=director)

        context = build_partner_contract_context(app, draft=False, director_user=director)

        assert context["signed_by_director"] is True
        assert context["director_email"] == director.email

    def test_resending_contract_drops_previous_agreement(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7733333334", is_active=True)
        app = agreed_app(company)

        response = post(supply, app, "send-contract")

        assert response.status_code == 200
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT
        assert app.candidate_agreed_at is None


class TestRejectClosesCandidateAccess:
    """(г) Первый вход отклонённого кандидата не делает его партнёром."""

    def test_rejected_candidate_loses_access_and_is_not_activated(self, supply):
        app = make_app()
        assert post(supply, app, "send-contract").status_code == 200
        app.refresh_from_db()
        company_id = app.company_id
        assert company_has_cabinet_access(company_id) is True

        assert post(supply, app, "reject", {"rejected_reason": "Не наш профиль"}).status_code == 200
        activate_on_first_login(company_id)

        assert not CompanyRelationship.objects.filter(company_id=company_id, status=RelationshipStatus.ACTIVE).exists()
        assert company_has_cabinet_access(company_id) is False

    def test_reject_does_not_touch_active_partner(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7733333335", is_active=True)
        rel = CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE, modules=["my_products"]
        )
        app = agreed_app(company)

        assert post(supply, app, "reject", {"rejected_reason": "Дубль"}).status_code == 200

        rel.refresh_from_db()
        assert rel.status == RelationshipStatus.ACTIVE and rel.modules == ["my_products"]

    def test_invited_with_modules_is_suspended_not_activated(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7733333336", is_active=True)
        rel = CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=["my_products"]
        )
        app = agreed_app(company)

        assert post(supply, app, "reject", {"rejected_reason": "Дубль"}).status_code == 200
        activate_on_first_login(company.pk)

        rel.refresh_from_db()
        assert rel.status == RelationshipStatus.SUSPENDED and rel.suspended_at is not None


class TestInvitationOutcome:
    """(д) Письмо не ушло — сотрудник это видит, заявка не считается отправленной."""

    def test_send_contract_reports_failed_handoff(self, supply, settings, monkeypatch):
        app = make_app()
        break_mail_handoff(settings, monkeypatch)

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "EMAIL_DELIVERY_FAILED"
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.SUBMITTED and app.company_id is None
        assert not Company.objects.filter(inn=app.inn).exists()

    def test_failed_delivery_is_shown_on_the_application(self, supply):
        app = make_app()
        assert post(supply, app, "send-contract").status_code == 200
        log = EmailLog.objects.filter(template="portal_invitation").latest("created_at")
        log.status = EmailLog.STATUS_FAILED
        log.save(update_fields=["status"])

        assert supply.get(f"{DESK}/{app.pk}/").json()["invite_delivery"] == "failed"
        assert supply.get(f"{DESK}/").json()["items"][0]["invite_delivery"] == "failed"

    def test_application_without_invitation_has_no_delivery(self, supply):
        app = make_app()
        assert supply.get(f"{DESK}/{app.pk}/").json()["invite_delivery"] is None

    def test_resend_invites_again(self, supply):
        app = make_app()
        assert post(supply, app, "send-contract").status_code == 200
        mail.outbox.clear()

        assert post(supply, app, "send-contract").status_code == 200

        assert len(mail.outbox) == 1


class TestApproveKeepsWhatIsThere:
    """(е) Одобрение не снимает приостановку, не трогает модули и не затирает сохранённую дату."""

    @pytest.fixture
    def company(self):
        return Company.objects.create(name="Партнёр", inn="7744444444", is_active=True)

    def test_suspended_partner_is_not_reactivated(self, supply, company):
        rel = CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.SUSPENDED, modules=["my_products"]
        )
        app = agreed_app(company)

        response = post(supply, app, "approve", {"contract_number": "D-1"})

        assert response.status_code == 400
        assert response.json()["detail"] == "PARTNER_SUSPENDED"
        rel.refresh_from_db()
        app.refresh_from_db()
        assert rel.status == RelationshipStatus.SUSPENDED
        assert app.status == PartnerApplicationStatus.CANDIDATE_AGREED

    def test_send_contract_refused_for_suspended_partner(self, supply, company):
        CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.SUSPENDED
        )
        app = make_app(inn=company.inn)

        response = post(supply, app, "send-contract", {"company_id": company.pk})

        assert response.status_code == 400
        assert response.json()["detail"] == "PARTNER_SUSPENDED"

    def test_modules_set_by_staff_are_kept(self, supply, company):
        rel = CompanyRelationship.objects.create(
            company=company,
            role=RelationshipRole.PARTNER,
            status=RelationshipStatus.ACTIVE,
            modules=["catalog_requests"],
        )
        app = agreed_app(company)

        assert post(supply, app, "approve", {"contract_number": "D-1"}).status_code == 200

        rel.refresh_from_db()
        assert rel.modules == ["catalog_requests"]

    def test_candidate_access_gets_default_modules(self, supply, company):
        rel = CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
        )
        app = agreed_app(company)

        assert post(supply, app, "approve", {"contract_number": "D-1"}).status_code == 200

        rel.refresh_from_db()
        assert set(rel.modules) == {"my_products", "catalog_requests"}

    def test_empty_date_does_not_erase_saved_one(self, supply, company):
        rel = CompanyRelationship.objects.create(
            company=company,
            role=RelationshipRole.PARTNER,
            status=RelationshipStatus.ACTIVE,
            modules=["my_products"],
            contract_date="2026-01-15",
        )
        app = agreed_app(company, contract_date="2026-01-15")

        assert post(supply, app, "approve", {"contract_number": "D-1"}).status_code == 200

        rel.refresh_from_db()
        app.refresh_from_db()
        assert str(rel.contract_date) == "2026-01-15"
        assert str(app.contract_date) == "2026-01-15"


class TestBindingIsNotRewritten:
    """Ревью #427: договор действующего партнёра и уже привязанная компания не меняются запросом."""

    def test_send_contract_keeps_contract_of_active_partner(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7746666666", is_active=True)
        rel = CompanyRelationship.objects.create(
            company=company,
            role=RelationshipRole.PARTNER,
            status=RelationshipStatus.ACTIVE,
            modules=["my_products"],
            contract_number="OLD-1",
            contract_date="2026-01-15",
        )
        app = make_app(inn=company.inn)

        response = post(supply, app, "send-contract", {"company_id": company.pk, "contract_number": "NEW-1"})
        assert response.status_code == 200
        assert post(supply, app, "reject", {"rejected_reason": "Передумали"}).status_code == 200

        rel.refresh_from_db()
        assert rel.contract_number == "OLD-1"
        assert str(rel.contract_date) == "2026-01-15"

    def test_invited_relationship_gets_contract_of_application(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7746666667", is_active=True)
        rel = CompanyRelationship.objects.create(
            company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
        )
        app = make_app(inn=company.inn)

        response = post(supply, app, "send-contract", {"company_id": company.pk, "contract_number": "NEW-2"})

        assert response.status_code == 200
        rel.refresh_from_db()
        assert rel.contract_number == "NEW-2"

    def test_approve_cannot_move_bound_application_to_another_company(self, supply):
        bound = Company.objects.create(name="Привязанная", inn="7746666668", is_active=True)
        other = Company.objects.create(name="Другая", inn="7746666669", is_active=True)
        rel = CompanyRelationship.objects.create(
            company=bound, role=RelationshipRole.PARTNER, status=RelationshipStatus.INVITED, modules=[]
        )
        app = agreed_app(bound)

        response = post(supply, app, "approve", {"contract_number": "D-1", "company_id": other.pk})

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MISMATCH"
        app.refresh_from_db()
        rel.refresh_from_db()
        assert app.company_id == bound.pk and app.status == PartnerApplicationStatus.CANDIDATE_AGREED
        assert rel.status == RelationshipStatus.INVITED
        assert not Contact.objects.filter(company=other).exists()
        assert not CompanyRelationship.objects.filter(company=other).exists()

    def test_send_contract_cannot_move_bound_application_to_another_company(self, supply):
        """B-FX1-1: `company_id` у привязанной заявки не игнорируется молча — ни для внешней заявки, ни для внутренней."""
        bound = Company.objects.create(name="Привязанная", inn="7746666671", is_active=True)
        other = Company.objects.create(name="Другая", inn="7746666672", is_active=True)
        app = agreed_app(bound)

        response = post(supply, app, "send-contract", {"company_id": other.pk, "contract_number": "D-2"})

        assert response.status_code == 400
        assert response.json()["detail"] == "COMPANY_MISMATCH"
        app.refresh_from_db()
        assert app.company_id == bound.pk and app.status == PartnerApplicationStatus.CANDIDATE_AGREED
        assert app.contract_number != "D-2"

    def test_rejected_application_archives_created_contact_without_rights(self, supply):
        """B-FX1-1: заведённый заявкой контакт в архиве не сохраняет `can_act` и `is_admin`."""
        app = make_app(inn="7746666673")
        assert post(supply, app, "send-contract", {"contract_number": "D-3"}).status_code == 200
        app.refresh_from_db()
        contact = app.applicant_contact
        assert contact.can_act is True and contact.is_admin is True
        assert post(supply, app, "reject", {"rejected_reason": "Передумали"}).status_code == 200
        contact.refresh_from_db()
        assert contact.is_archived and contact.can_act is False and contact.is_admin is False

    def test_approve_with_the_same_bound_company_goes_through(self, supply):
        bound = Company.objects.create(name="Привязанная", inn="7746666670", is_active=True)
        app = agreed_app(bound)

        assert post(supply, app, "approve", {"contract_number": "D-1", "company_id": bound.pk}).status_code == 200


class TestRejectArchivesCreatedContact:
    """Решение архитектора по #427: контакт, заведённый этой заявкой и ни с чем больше не связанный, снимается при отклонении."""

    def sent(self, supply, **kwargs) -> PartnerApplication:
        app = make_app(**kwargs)
        assert post(supply, app, "send-contract", {}).status_code == 200
        app.refresh_from_db()
        return app

    def test_contact_created_by_application_is_archived(self, supply):
        app = self.sent(supply)
        contact = app.applicant_contact

        assert post(supply, app, "reject", {"rejected_reason": "Не наш профиль"}).status_code == 200

        contact.refresh_from_db()
        assert contact.is_archived

    def test_contact_created_in_confirmed_company_is_archived(self, supply, victim):
        app = make_app(inn=victim.inn, email="owner@victim.example")
        assert post(supply, app, "send-contract", {"company_id": victim.pk}).status_code == 200
        app.refresh_from_db()

        assert post(supply, app, "reject", {"rejected_reason": "Не подтвердили"}).status_code == 200

        contact = Contact.objects.get(company=victim, email="owner@victim.example")
        assert contact.is_archived

    def test_existing_contact_of_the_company_is_kept(self, supply, victim):
        existing = Contact.objects.create(company=victim, name="Сотрудник", email="staff@victim.example", can_act=True)
        app = make_app(inn=victim.inn, email="staff@victim.example")
        assert post(supply, app, "send-contract", {"company_id": victim.pk}).status_code == 200
        app.refresh_from_db()
        assert app.applicant_contact_id == existing.pk

        assert post(supply, app, "reject", {"rejected_reason": "Дубль"}).status_code == 200

        existing.refresh_from_db()
        assert not existing.is_archived

    def test_contact_with_another_open_application_is_kept(self, supply):
        app = self.sent(supply)
        contact = app.applicant_contact
        make_app(
            company=app.company,
            applicant_contact=contact,
            company_name="Другая заявка",
            inn="7777000001",
            status=PartnerApplicationStatus.CONTRACT_SENT,
        )

        assert post(supply, app, "reject", {"rejected_reason": "Дубль"}).status_code == 200

        contact.refresh_from_db()
        assert not contact.is_archived

    def test_contact_linked_to_crm_is_kept(self, supply):
        from integration.models import CrmContactMapping

        app = self.sent(supply)
        contact = app.applicant_contact
        CrmContactMapping.objects.create(crm_contact_id=98765, contact=contact)

        assert post(supply, app, "reject", {"rejected_reason": "Дубль"}).status_code == 200

        contact.refresh_from_db()
        assert not contact.is_archived


class TestRenderFailure:
    """(ж) Сбой WeasyPrint — ошибка, заглушка договором не сохраняется."""

    @pytest.fixture
    def broken_renderer(self, monkeypatch):
        import weasyprint

        def explode(*args, **kwargs):
            raise OSError("cairo is gone")

        monkeypatch.setattr(weasyprint, "HTML", explode)

    @pytest.mark.usefixtures("broken_renderer")
    def test_render_raises_instead_of_stub(self):
        with pytest.raises(PartnerContractRenderError):
            render_partner_contract_pdf(make_app(), draft=True)

    @pytest.mark.usefixtures("broken_renderer")
    def test_send_contract_saves_nothing(self, supply):
        app = make_app()

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "CONTRACT_RENDER_FAILED"
        app.refresh_from_db()
        assert not app.contract_pdf and app.status == PartnerApplicationStatus.SUBMITTED
        assert mail.outbox == []

    @pytest.mark.usefixtures("broken_renderer")
    def test_approve_saves_nothing(self, supply):
        company = Company.objects.create(name="Партнёр", inn="7755555555", is_active=True)
        app = agreed_app(company)

        response = post(supply, app, "approve", {"contract_number": "D-1"})

        assert response.status_code == 400
        assert response.json()["detail"] == "CONTRACT_RENDER_FAILED"
        app.refresh_from_db()
        assert not app.contract_pdf and app.status == PartnerApplicationStatus.CANDIDATE_AGREED
        assert not CompanyRelationship.objects.filter(company=company).exists()

    @pytest.mark.usefixtures("broken_renderer")
    def test_agree_saves_nothing(self, portal_client, client_company, client_contact):
        app = make_app(
            source=PartnerApplicationSource.CLIENT_CABINET,
            company=client_company,
            applicant_contact=client_contact,
            status=PartnerApplicationStatus.CONTRACT_SENT,
        )

        response = portal_client.post(f"{PORTAL}/agree", {"notes": ""}, format="json")

        assert response.status_code == 503
        assert response.json()["detail"] == "DOCUMENT_PENDING"
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT
        assert app.candidate_agreed_at is None and not app.contract_pdf

    @pytest.mark.usefixtures("broken_renderer")
    def test_download_does_not_store_stub(self, portal_client, client_company, client_contact):
        app = make_app(
            source=PartnerApplicationSource.CLIENT_CABINET,
            company=client_company,
            applicant_contact=client_contact,
            status=PartnerApplicationStatus.CONTRACT_SENT,
        )

        response = portal_client.get(f"{PORTAL}/contract-pdf")

        assert response.status_code == 503
        app.refresh_from_db()
        assert not app.contract_pdf


class TestLongInn:
    """(з) ИНН длиннее поля компании — отказ кодом, а не ошибка базы."""

    LONG = "1" * 25

    def public_payload(self, **kwargs):
        return {
            "company_name": "ООО Длинный",
            "categories_description": "Поставка запасных частей",
            "contact_name": "Иван",
            "email": "long@applicant.example",
            "consent": True,
            "website": "",
            **kwargs,
        }

    def test_public_form_rejects_long_inn(self, anon_portal_client):
        response = anon_portal_client.post(PUBLIC, self.public_payload(inn=self.LONG), format="json")

        assert response.status_code == 422
        assert response.json()["detail"] == "VALIDATION_ERROR"
        assert not PartnerApplication.objects.exists()

    def test_foreign_long_number_becomes_registration_number(self, anon_portal_client):
        from core.models import Country

        Country.objects.get_or_create(code="DE", defaults={"name": "Germany"})
        response = anon_portal_client.post(PUBLIC, self.public_payload(inn=self.LONG, country="DE"), format="json")

        assert response.status_code == 201
        assert PartnerApplication.objects.get().registration_number == self.LONG

    def test_foreign_long_inn_next_to_registration_number_is_rejected(self, anon_portal_client):
        response = anon_portal_client.post(
            PUBLIC, self.public_payload(inn=self.LONG, country="DE", registration_number="HRB-9"), format="json"
        )

        assert response.status_code == 422

    def test_send_contract_refuses_already_stored_long_inn(self, supply):
        app = make_app(inn=self.LONG)

        response = post(supply, app, "send-contract")

        assert response.status_code == 400
        assert response.json()["detail"] == "INN_TOO_LONG"

    def test_approve_refuses_already_stored_long_inn(self, supply):
        app = make_app(inn=self.LONG, status=PartnerApplicationStatus.CONTRACT_SENT)

        response = post(supply, app, "approve", {"contract_number": "D-1", "override_reason": "бумага"})

        assert response.status_code == 400
        assert response.json()["detail"] == "INN_TOO_LONG"


class TestCandidateReachesOwnApplication:
    """(и) У кандидата нет модуля `company`, но своя заявка, договор и согласование ему доступны."""

    @pytest.fixture
    def candidate(self):
        company, contact, client = candidate_session()
        app = make_app(
            company=company,
            applicant_contact=contact,
            company_name=company.name,
            inn=company.inn,
            email=contact.email,
            status=PartnerApplicationStatus.CONTRACT_SENT,
            contract_number="PART-1",
        )
        return client, app

    def test_status_is_available(self, candidate):
        client, app = candidate
        response = client.get(PORTAL)
        assert response.status_code == 200
        assert response.json()["application"]["id"] == app.pk

    def test_contract_pdf_is_available(self, candidate):
        client, _app = candidate
        response = client.get(f"{PORTAL}/contract-pdf")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"

    def test_candidate_can_agree(self, candidate):
        client, app = candidate
        response = client.post(f"{PORTAL}/agree", {"notes": "Согласовано"}, format="json")
        assert response.status_code == 200
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CANDIDATE_AGREED

    def test_candidate_without_can_act_cannot_agree(self):
        company, _contact, _client = candidate_session()
        viewer = Contact.objects.create(company=company, name="Наблюдатель", email="v@candidate.example", can_act=False)
        make_app(company=company, status=PartnerApplicationStatus.CONTRACT_SENT)

        response = session_client(viewer, company).post(f"{PORTAL}/agree", {"notes": ""}, format="json")

        assert response.status_code == 403
