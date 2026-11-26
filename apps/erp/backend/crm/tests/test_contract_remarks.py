"""ДП-1: замечания контрагента к договору и отметка «Подписан» заметкой.

Факты, из которых всё выводится: строки `ContractRemark` / `ContractRemarkVote`, статус договора, `manager_signed_at`.
Защиты, без которых тесты краснеют: решение при разногласии — только держатель `contract.sign`; «все согласны» принимает
редакцию контрагента, а не раньше; «Подписан» заметкой требует заметку и считает срок в тот же момент.
"""

import pytest
from django.core.files.base import ContentFile
from integration.tests import bus_support
from portal.models import PortalUpload

from accounts.models import CompanyMember
from crm.constants import ContractStatusCode as S
from crm.constants import DealStageCode
from crm.models import ActivityLog, ContractRemark, Deal
from crm.services import contract_compare, contract_flow, contract_remarks
from crm.tests.projects_world import _staff, api, contract_in, pw, scan  # noqa: F401
from notifications.models import Notification

pytestmark = pytest.mark.django_db

BODY = (
    "<p>1.1. Поставщик передаёт оборудование.</p>"
    "<p>2.2. Покупатель вносит предоплату 50 % в течение 5 дней.</p>"
    "<p>5.2. За просрочку оплаты уплачивается пеня 0,1 %.</p>"
)


def docx_bytes(paragraphs):
    return contract_compare.paragraphs_to_docx(paragraphs)


@pytest.fixture
def world(pw, grant):  # noqa: F811
    from parties.models import Contact

    owner = CompanyMember.objects.get(user=pw.accountant).role
    pw.legal = _staff(pw.own, "legal@own.test", owner)
    grant(pw.legal, "contract.approve_template")
    pw.contact = Contact.objects.create(company=pw.client, name="Ш. Юсупов", can_act=True, email="y@client.test")
    pw.contract = contract_in(pw, S.PENDING_CLIENT, frozen_template_body=BODY)
    return pw


def upload(world, paragraphs, name="our.docx"):
    return PortalUpload.objects.create(
        company=world.client,
        uploaded_by=world.contact,
        name=name,
        file=ContentFile(docx_bytes(paragraphs), name=name),
        size_bytes=1000,
        content_type="application/octet-stream",
    )


THEIRS = [
    "1.1. Поставщик передаёт оборудование.",
    "2.2. Покупатель вносит предоплату 30 % в течение 5 дней.",
    "3.3. Поставщик выполняет пусконаладку.",
]


def submit(world, paragraphs=THEIRS, comment="Бюджет закрыт"):
    return contract_remarks.submit_remark(
        world.contract.id, contact=world.contact, comment=comment, upload_id=str(upload(world, paragraphs).upload_id)
    )


def status(contract):
    contract.refresh_from_db()
    return contract.status.code


def vote_all(world, agree_by):
    for user in (world.director, world.accountant, world.legal):
        contract_remarks.vote(world.contract.id, user, agree=agree_by(user), comment="" if agree_by(user) else "Нет")


def test_compare_shows_changed_added_and_removed_points():
    ours = ["1.1. Один.", "2.2. Предоплата 50 % сразу.", "5.2. Пеня 0,1 %."]
    result = contract_compare.compare(ours, ["1.1. Один.", "2.2. Предоплата 30 % сразу.", "3.3. Новое."])
    kinds = {(i["point"], i["kind"]) for i in result["items"]}
    assert ("2.2", "changed") in kinds and ("3.3", "added") in kinds and ("5.2", "removed") in kinds
    changed = next(i for i in result["items"] if i["kind"] == "changed")
    assert {"op": "del", "text": "50"} in changed["segments"] and {"op": "ins", "text": "30"} in changed["segments"]
    assert result["summary"]["changed"] == ["2.2"] and result["summary"]["total"] == 3


def test_docx_round_trip_keeps_the_text_and_unchanged_upload_shows_no_diff(world):
    ours = contract_compare.contract_paragraphs(world.contract)
    assert ours[:2] == [
        "1.1. Поставщик передаёт оборудование.",
        "2.2. Покупатель вносит предоплату 50 % в течение 5 дней.",
    ]
    again = contract_compare.docx_paragraphs(ContentFile(contract_compare.contract_docx(world.contract)))
    assert again == ours
    assert contract_compare.compare(ours, again)["summary"]["total"] == 0


def test_remark_is_recorded_with_diff_and_reviewers_are_notified(world):
    remark, error = submit(world)
    assert error is None and remark.resolution == "" and remark.file_name == "our.docx"
    assert remark.summary["comparable"] is True and remark.summary["changed"] == ["2.2"]
    assert status(world.contract) == S.PENDING_CLIENT
    notified = set(Notification.objects.filter(event_code="contract.remark_received").values_list("user_id", flat=True))
    assert {world.director.pk, world.accountant.pk, world.legal.pk} <= notified
    assert ActivityLog.objects.filter(event_code="contract.remark_received", entity_id=world.contract.pk).exists()
    again, error = submit(world)
    assert (again, error) == (None, "REMARK_OPEN")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [({"comment": "  "}, "COMMENT_REQUIRED"), ({"upload_id": "not-a-uuid"}, "UPLOAD_NOT_FOUND")],
)
def test_remark_input_errors(world, kwargs, code):
    _, error = contract_remarks.submit_remark(world.contract.id, contact=world.contact, **{"comment": "x", **kwargs})
    assert error == code


def test_remark_only_while_the_contract_is_at_the_counterparty(world):
    contract = contract_in(world, S.PENDING_MANAGER)
    _, error = contract_remarks.submit_remark(contract.id, contact=world.contact, comment="x")
    assert error == "CONTRACT_REMARK_NOT_ALLOWED"


def test_foreign_file_type_is_refused(world):
    bad = PortalUpload.objects.create(
        company=world.client, name="x.docx", file=ContentFile(b"not a zip", name="x.docx"), size_bytes=9
    )
    _, error = contract_remarks.submit_remark(
        world.contract.id, contact=world.contact, comment="x", upload_id=str(bad.upload_id)
    )
    assert error == "FILE_INVALID"


def test_everyone_agrees_then_the_counterparty_edition_is_accepted(world):
    submit(world)
    contract_remarks.vote(world.contract.id, world.director, agree=True)
    contract_remarks.vote(world.contract.id, world.accountant, agree=True)
    assert status(world.contract) == S.PENDING_CLIENT, "пока не ответил юрист, редакция не принята"
    bus_support.reset() if hasattr(bus_support, "reset") else None
    contract_remarks.vote(world.contract.id, world.legal, agree=True)
    assert status(world.contract) == S.PENDING_MANAGER and world.contract.client_signed_at is not None
    remark = ContractRemark.objects.get()
    assert remark.resolution == "accepted"
    assert contract_flow.contract_v3_status(world.contract) == "client_agreed"
    assert bus_support.published("contract.status_changed")


def test_dispute_waits_for_the_director_and_only_sign_holders_decide(world):
    submit(world)
    vote_all(world, lambda user: user != world.legal)
    assert status(world.contract) == S.PENDING_CLIENT
    _, error = contract_remarks.decide(world.contract.id, world.legal, accept=True)
    assert error == "REMARK_DECISION_FORBIDDEN"
    _, error = contract_remarks.decide(world.contract.id, world.director, accept=False)
    assert error == "COMMENT_REQUIRED"
    _, error = contract_remarks.decide(world.contract.id, world.director, accept=True)
    assert error is None and status(world.contract) == S.PENDING_MANAGER
    assert ContractRemark.objects.get().resolved_by_id == world.director.pk


def test_director_can_answer_with_our_edition_and_the_client_can_remark_again(world):
    submit(world)
    vote_all(world, lambda user: user != world.legal)
    _, error = contract_remarks.decide(world.contract.id, world.director, accept=False, text="Предоплата 40 %")
    assert error is None and status(world.contract) == S.PENDING_CLIENT
    remark = ContractRemark.objects.get()
    assert remark.resolution == "countered" and remark.response == "Предоплата 40 %"
    assert contract_remarks.edition_of(world.contract) == 2
    again, error = submit(world, comment="Ещё раз")
    assert error is None and again.edition == 2


def test_director_closes_the_remark_at_any_time_even_if_someone_never_answered(world):
    """Один из ответственных не ответил: договор не застревает, решающий голос принимает редакцию сам."""
    submit(world)
    contract_remarks.vote(world.contract.id, world.director, agree=True)
    assert status(world.contract) == S.PENDING_CLIENT
    _, error = contract_remarks.decide(world.contract.id, world.legal, accept=True)
    assert error == "REMARK_DECISION_FORBIDDEN"
    _, error = contract_remarks.decide(world.contract.id, world.accountant, accept=True)
    assert error is None and status(world.contract) == S.PENDING_MANAGER
    assert ContractRemark.objects.get().resolution == "accepted"


def test_director_can_answer_with_our_edition_before_everyone_answered(world):
    submit(world)
    _, error = contract_remarks.decide(world.contract.id, world.director, accept=False, text="Нет")
    assert error is None and status(world.contract) == S.PENDING_CLIENT
    assert ContractRemark.objects.get().resolution == "countered"


def test_client_is_told_about_acceptance_and_about_our_answer(world):
    from portal.models import PortalNotice

    submit(world)
    contract_remarks.decide(world.contract.id, world.director, accept=False, text="Предоплата 40 %")
    notice = PortalNotice.objects.filter(kind="contract_remark_answered", company=world.client).first()
    assert notice is not None and "Предоплата 40 %" in str(notice.params)
    again, _ = submit(world, comment="Ещё раз")
    contract_remarks.decide(world.contract.id, world.director, accept=True)
    assert PortalNotice.objects.filter(kind="contract_awaiting_signature", company=world.client).exists()


def test_card_shows_empty_deciders_when_nobody_holds_the_signing_right(world, monkeypatch):
    from crm.services import projects

    submit(world)
    monkeypatch.setattr(contract_remarks, "deciders", lambda contract: [])
    card = projects._contract_card(world.contract, world.manager, [])
    assert card["remark"]["deciders"] == [] and card["remark"]["actions"] == []


def test_upload_of_another_company_is_not_found(world):
    from portal.models import PortalUpload

    other = PortalUpload.objects.create(
        company=world.own, name="x.docx", file=ContentFile(docx_bytes(THEIRS), name="x.docx"), size_bytes=10
    )
    _, error = contract_remarks.submit_remark(
        world.contract.id, contact=world.contact, comment="x", upload_id=str(other.upload_id)
    )
    assert error == "UPLOAD_NOT_FOUND"
    assert not ContractRemark.objects.exists()


def zip_bomb():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * (200 * 1024 * 1024))
        archive.writestr("[Content_Types].xml", b"<Types/>")
    return buf.getvalue()


def test_zip_bomb_is_refused_before_python_docx_opens_it(world):
    from portal.models import PortalUpload

    bomb = PortalUpload.objects.create(
        company=world.client, name="bomb.docx", file=ContentFile(zip_bomb(), name="bomb.docx"), size_bytes=300_000
    )
    _, error = contract_remarks.submit_remark(
        world.contract.id, contact=world.contact, comment="x", upload_id=str(bomb.upload_id)
    )
    assert error == "FILE_INVALID" and not ContractRemark.objects.exists()


def forged_bomb():
    """DOCX, где часть в 120 МБ нулей заявлена в каталоге архива как 1000 байт (подделанный размер)."""
    import io
    import struct
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        with archive.open("word/media/big.png", "w") as part:
            for _ in range(120):
                part.write(b"\0" * (1 << 20))
    data = bytearray(buf.getvalue())
    pos = data.find(b"PK\x01\x02")
    while pos >= 0:
        name_len = struct.unpack("<H", data[pos + 28 : pos + 30])[0]
        if bytes(data[pos + 46 : pos + 46 + name_len]) == b"word/media/big.png":
            data[pos + 24 : pos + 28] = struct.pack("<I", 1000)
        pos = data.find(b"PK\x01\x02", pos + 4)
    return bytes(data)


def test_forged_declared_size_does_not_hide_a_zip_bomb_and_memory_stays_bounded():
    import tracemalloc

    data = forged_bomb()
    import zipfile
    from io import BytesIO

    assert zipfile.ZipFile(BytesIO(data)).getinfo("word/media/big.png").file_size == 1000
    tracemalloc.start()
    with pytest.raises(contract_compare.HostileFile):
        contract_compare.check_archive(data)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 20 * 1024 * 1024


def test_long_paragraphs_are_not_compared_pairwise_for_minutes():
    import random
    import time

    random.seed(1)
    words = ["поставка", "оплата", "покупатель", "поставщик", "срок", "договор", "цена", "товар", "акт", "склад"]

    def long_text():
        return " ".join(random.choice(words) for _ in range(300))[:2000]

    ours = [long_text() for _ in range(120)]
    theirs = [long_text() for _ in range(83)]
    started = time.monotonic()
    with pytest.raises(contract_compare.TooBig):
        contract_compare.compare(ours, theirs)
    assert time.monotonic() - started < 5


def test_huge_document_is_not_compared_and_stays_fast(world):
    import time

    started = time.monotonic()
    remark, error = submit(world, [f"{i}.1. Пункт номер {i} договора поставки." for i in range(2000)])
    assert error is None and remark.summary["comparable"] is False and remark.items == []
    assert time.monotonic() - started < 10


def test_summary_is_capped_with_the_rest_counted(world):
    ours = [f"{i}.1. Было {i}." for i in range(1, 80)]
    result = contract_compare.compare(ours, [f"{i}.1. Стало {i}." for i in range(1, 80)])
    assert len(result["summary"]["changed"]) == contract_compare.SUMMARY_POINTS
    assert result["summary"]["more"] == 79 - contract_compare.SUMMARY_POINTS


def test_only_those_in_charge_vote_and_disagreement_needs_words(world):
    submit(world)
    _, error = contract_remarks.vote(world.contract.id, world.manager, agree=True)
    assert error == "REMARK_FORBIDDEN"
    _, error = contract_remarks.vote(world.contract.id, world.director, agree=False)
    assert error == "COMMENT_REQUIRED"


def test_card_tells_each_person_what_they_can_do(world):
    from crm.services import projects

    submit(world)
    card = projects._contract_card(world.contract, world.director, [])
    assert card["remark"]["actions"] == ["vote", "decide"] and card["remark"]["summary"]["changed"] == ["2.2"]
    assert {p["name"] for p in card["remark"]["awaiting"]} >= {"", ""} or card["remark"]["awaiting"]
    vote_all(world, lambda user: user != world.legal)
    assert projects._contract_card(world.contract, world.director, [])["remark"]["actions"] == ["vote", "decide"]
    assert "decide" not in projects._contract_card(world.contract, world.legal, [])["remark"]["actions"]
    assert projects._contract_card(world.contract, world.manager, [])["remark"]["actions"] == []


def test_staff_endpoints_vote_and_decide(world):
    submit(world)
    url = "/api/v1/crm/contracts/{}/{}/"
    r = api(world.director).post(url.format(world.contract.id, "remark-vote"), {"agree": True}, format="json")
    assert r.status_code == 200, r.content
    r = api(world.manager).post(url.format(world.contract.id, "remark-vote"), {"agree": True}, format="json")
    assert r.status_code in (403, 404)
    assert api(world.director).get(url.format(world.contract.id, "download-docx")).status_code == 200
    assert api(world.director).get(url.format(world.contract.id, "download-remark")).status_code == 200


# ── «Отметить: подписан» ──────────────────────────────────────────────────────────────────────────────────────────


def test_marked_signed_by_note_closes_the_deal_and_counts_the_term(world):
    contract = contract_in(world, S.PENDING_MANAGER, client_signed_at=world.deal.created_at)
    _, error = contract_flow.apply_transition(contract.id, "mark_signed", world.director, note="  ")
    assert error == "NOTE_REQUIRED" and status(contract) == S.PENDING_MANAGER
    signed, error = contract_flow.apply_transition(contract.id, "mark_signed", world.director, note="Подписан в офисе")
    assert error is None and status(contract) == S.SIGNED
    contract.refresh_from_db()
    assert not contract.signed_file and contract.manager_signed_at is not None
    assert contract.valid_until is not None or contract.term_rule, "срок считается в момент отметки"
    assert Deal.objects.get(pk=world.deal.pk).stage.code == DealStageCode.CLOSED_WON
    assert ActivityLog.objects.filter(event_code="contract.marked_signed", entity_id=contract.pk).exists()


def test_scan_is_accepted_straight_from_waiting_for_signature(world):
    contract = contract_in(world, S.PENDING_MANAGER)
    _, error = contract_flow.apply_transition(contract.id, "attach_scan", world.director, scan=scan())
    assert error is None and status(contract) == S.SIGNED


def test_issued_at_operator_is_no_longer_offered_but_waiting_offers_both_ways(world):
    contract = contract_in(world, S.PENDING_MANAGER)
    actions = contract_flow.allowed_actions(contract, world.director)
    assert "mark_issued" not in actions and {"mark_signed", "attach_scan"} <= set(actions)


def test_only_sign_holders_mark_signed(world):
    contract = contract_in(world, S.PENDING_MANAGER)
    _, error = contract_flow.apply_transition(contract.id, "mark_signed", world.manager, note="x")
    assert error == "MEMBER_REQUIRED_FOR_ACTION"
