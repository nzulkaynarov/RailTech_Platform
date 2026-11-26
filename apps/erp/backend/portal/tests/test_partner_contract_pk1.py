# flake8: noqa: F811
"""ПК-1: договор партнёра — общий путь с клиентом: голоса ответственных и директор на разногласии, «Есть замечания» с
редакцией кандидата, срок при отметке «подписан».

Защиты, без которых тесты краснеют (мутационная проверка в PR): `_resolve` (все согласны / директор решает),
`CONTRACT_DIRECTOR_DECIDES`, `apply_to_partner_application` в `approve_application`, проверка файла редакции кандидата.
"""

import datetime

import pytest
from parties.models import PartnerApplicationStatus
from parties.models.company_settings import CompanySettings
from portal.tests.partner_contract_helpers import PDF
from portal.tests.test_partner_contract_pd1 import (  # noqa: F401
    DESK,
    PORTAL,
    _locmem_mail,
    director,
    make_app,
    post,
    session_client,
    set_default,
    supply,
    template,
    upload,
    world,
)

from catalog.tests.desk_world import client_for, make_staff
from notifications.models import Notification

pytestmark = pytest.mark.django_db

DOCX = b"PK\x03\x04" + b"\x00" * 64


def _own_file(supply):
    app = make_app()
    response = supply.post(f"{DESK}/{app.pk}/prepare-contract/", {"file": upload()}, format="multipart")
    assert response.status_code == 200, response.content
    return app


def _lawyer(world):
    """Ответственный без права подписи: право утверждать договоры есть, директором он не является."""
    return make_staff(world["own"], "director", permissions=["contract.approve_template"], label="lawyer")


class TestEveryoneApprovesDirectorDecides:
    def test_contract_is_approved_only_when_every_responsible_has_approved(self, world, supply, director):
        lawyer = _lawyer(world)
        app = _own_file(supply)

        assert post(client_for(lawyer), app, "contract-decision", {"decision": "approve"}).status_code == 200
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert card["contract_approval"] == "requested", "директор ещё не высказался"
        assert [v["decision"] for v in card["contract_votes"]] == ["approve"]
        assert card["contract_waiting_for"] == [director_name(world)]

        assert post(director, app, "contract-decision", {"decision": "approve"}).status_code == 200
        assert supply.get(f"{DESK}/{app.pk}/").json()["contract_approval"] == "approved"

    def test_disagreement_is_decided_by_the_director_not_by_counting(self, world, supply, director):
        lawyer = _lawyer(world)
        app = _own_file(supply)

        assert (
            post(
                client_for(lawyer), app, "contract-decision", {"decision": "return", "note": "Срок оплаты"}
            ).status_code
            == 200
        )
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert card["contract_approval"] == "requested" and card["contract_disagreement"] is True
        assert card["contract_waiting_for"] == [director_name(world)]
        assert Notification.objects.filter(event_code="partner_contract.disagreement").exists()
        # тот, кто возразил, второй раз не решает: слово за директором
        again = post(client_for(lawyer), app, "contract-decision", {"decision": "approve"})
        assert again.status_code == 403 and again.json()["detail"] == "CONTRACT_DIRECTOR_DECIDES"

        assert post(director, app, "contract-decision", {"decision": "approve"}).status_code == 200
        assert supply.get(f"{DESK}/{app.pk}/").json()["contract_approval"] == "approved"

    def test_director_may_return_at_once(self, world, supply, director):
        _lawyer(world)
        app = _own_file(supply)

        response = post(director, app, "contract-decision", {"decision": "return", "note": "Нет"})

        assert response.status_code == 200
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert card["contract_approval"] == "returned" and card["contract_approval_note"] == "Нет"


class TestAgreeWhileOurApprovalPending:
    def test_candidate_cannot_agree_while_our_approval_of_his_edition_is_requested(self, world, supply, director):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app()
        post(supply, app, "prepare-contract", {"language": "ru"})
        assert post(supply, app, "send-contract").status_code == 200
        app.refresh_from_db()
        app.contract_approval = "requested"
        app.save()
        cabinet = session_client(app.applicant_contact, app.company)

        refused = cabinet.post(f"{PORTAL}/agree/", {}, format="json")

        assert refused.status_code == 400
        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT


class TestSignOnlyHolder:
    """Держатель только `contract.sign` — обязательный голос и решающий: гейт вьюхи его пускает."""

    def test_holder_of_sign_only_votes_and_decides(self, world, supply, director):
        signer = make_staff(world["own"], "director", permissions=["contract.sign"], label="signer")
        lawyer = _lawyer(world)
        app = _own_file(supply)

        # голос: до исправления гейт вьюхи отвечал 403 ROLE_NOT_PERMITTED
        voted = post(client_for(signer), app, "contract-decision", {"decision": "approve"})
        assert voted.status_code == 200, voted.content
        # разногласие: решает держатель подписи
        assert (
            post(client_for(lawyer), app, "contract-decision", {"decision": "return", "note": "Срок"}).status_code
            == 200
        )
        decided = post(client_for(signer), app, "contract-decision", {"decision": "approve"})
        assert decided.status_code == 200, decided.content
        assert supply.get(f"{DESK}/{app.pk}/").json()["contract_approval"] == "approved"


def director_name(world):
    user = world["users"]["director"]
    return (user.get_full_name() or user.email).strip()


class TestCandidateRemarksWindow:
    def _sent(self, world, supply):
        tpl = template(world)
        set_default(world, tpl)
        app = make_app()
        post(supply, app, "prepare-contract", {"language": "ru"})
        assert post(supply, app, "send-contract").status_code == 200
        app.refresh_from_db()
        return app, session_client(app.applicant_contact, app.company)

    def test_remarks_with_own_docx_become_the_contract_under_approval(self, world, supply):
        app, candidate = self._sent(world, supply)
        docx = upload("my.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        response = candidate.post(
            f"{PORTAL}/return", {"notes": "Срок оплаты 60 дней", "file": docx}, format="multipart"
        )

        assert response.status_code == 200, response.content
        app.refresh_from_db()
        assert app.candidate_file and app.contract_file.read() == DOCX
        assert app.contract_source == "upload" and app.contract_approval == "requested"
        card = supply.get(f"{DESK}/{app.pk}/").json()
        assert card["has_candidate_file"] is True and card["contract_blocker"] == "CONTRACT_APPROVAL_PENDING"
        assert post(supply, app, "send-contract").json()["detail"] == "CONTRACT_APPROVAL_PENDING"
        assert supply.get(f"{DESK}/{app.pk}/document/?which=candidate").content == DOCX
        assert Notification.objects.filter(event_code="partner_contract.remarks", user=world["users"]["director"])

    def test_remarks_need_a_comment_or_a_file_and_a_valid_file(self, world, supply):
        app, candidate = self._sent(world, supply)

        assert candidate.post(f"{PORTAL}/return", {"notes": ""}, format="json").status_code == 400
        bad = candidate.post(
            f"{PORTAL}/return",
            {"notes": "x", "file": upload("a.exe", b"MZ", "application/octet-stream")},
            format="multipart",
        )
        assert bad.status_code == 400 and bad.json()["detail"] == "CONTRACT_FILE_INVALID"
        app.refresh_from_db()
        assert not app.candidate_file and app.candidate_returned_at is None

    def test_plain_comment_still_works_and_informs_the_responsible(self, world, supply):
        app, candidate = self._sent(world, supply)

        assert candidate.post(f"{PORTAL}/return", {"notes": "Правки"}, format="json").status_code == 200

        assert Notification.objects.filter(event_code="partner_contract.remarks").exists()


class TestSignedTerm:
    def test_term_is_computed_when_marked_signed_by_the_company_rule(self, world, supply):
        tpl = template(world)
        set_default(world, tpl)
        row = CompanySettings.objects.get(company=tpl.company)
        row.contract_term_rule = "twelve_months"
        row.save()
        app = make_app()
        post(supply, app, "prepare-contract", {"language": "ru"})
        post(supply, app, "send-contract")
        app.refresh_from_db()
        session_client(app.applicant_contact, app.company).post(f"{PORTAL}/agree", {}, format="json")

        response = post(supply, app, "approve", {"contract_number": app.contract_number, "signed_note": "Подписан"})

        assert response.status_code == 200, response.content
        app.refresh_from_db()
        today = datetime.date.today()
        assert app.contract_valid_from == today and app.contract_term_rule == "twelve_months"
        assert app.contract_valid_until > today and app.status == PartnerApplicationStatus.APPROVED
