"""«Кто вправе подписать вид X на сумму Y на дату D»: все ветки подбора без базы (ADR-0024 п. 2–3).

Лимит, срок, отзыв, валюта, отключённый владелец, замещение (в том числе без собственного полномочия — прав не даёт),
цепочка и петля заместителей, порядок кандидатов и объяснение.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.schemas.signing import SigningResolution
from app.services.signing_resolve import Grant, Holder, basis_text, evaluate, signer_check

DAY = date(2026, 11, 10)
DIRECTOR, DEPUTY, CLERK, MANAGER = 3, 4, 5, 6


def people(**overrides: Holder) -> dict[int, Holder]:
    base = {
        DIRECTOR: Holder(DIRECTOR, "Рустам Директоров", "Директор", True),
        DEPUTY: Holder(DEPUTY, "Дилшод Замов", "Заместитель директора", True),
        CLERK: Holder(CLERK, "Регина Регистраторова", "Делопроизводитель", True),
        MANAGER: Holder(MANAGER, "Алия Каримова", "Менеджер", True),
    }
    return base | {int(k.removeprefix("u")): v for k, v in overrides.items()}


def grant(
    user: int,
    *kinds: str,
    basis: str = "charter",
    limit: str | None = None,
    currency: str | None = None,
    start: date = date(2026, 1, 1),
    end: date | None = None,
    number: str | None = None,
    issued: date | None = None,
    revoked: bool = False,
) -> Grant:
    return Grant(
        id=uuid.uuid4(),
        crm_user_id=user,
        kinds=kinds or ("letter_out",),
        limit_amount=None if limit is None else Decimal(limit),
        limit_currency=currency,
        basis=basis,
        basis_number=number,
        basis_date=issued,
        valid_from=start,
        valid_to=end,
        revoked=revoked,
    )


def poa(user: int, *kinds: str, number: str = "17", **kw: object) -> Grant:
    kw.setdefault("issued", date(2026, 3, 1))
    kw.setdefault("start", date(2026, 3, 1))
    kw.setdefault("end", date(2027, 3, 1))
    return grant(user, *kinds, basis="power_of_attorney", number=number, **kw)  # type: ignore[arg-type]


def run(
    grants: list[Grant],
    *,
    kind: str = "letter_out",
    amount: str | None = None,
    currency: str | None = None,
    on: date = DAY,
    staff: dict[int, Holder] | None = None,
) -> SigningResolution:
    return evaluate(
        kind=kind,
        amount=None if amount is None else Decimal(amount),
        currency=currency,
        on_date=on,
        grants=grants,
        people=staff or people(),
        kind_label=kind,
    )


def ids(result: SigningResolution) -> list[int]:
    return [c.signer.crm_user_id for c in result.candidates]


def reasons(result: SigningResolution) -> dict[int, str]:
    return {r.signer.crm_user_id: r.reason for r in result.rejected}


# --- основания, сроки, отзыв, виды ---------------------------------------------------------------------------------


def test_charter_holder_may_sign_the_kind() -> None:
    result = run([grant(DIRECTOR, "letter_out", "contract")])
    assert result.resolved and ids(result) == [DIRECTOR]
    candidate = result.candidates[0]
    assert candidate.acting_for == [] and candidate.basis_text is None
    assert [s.code for s in result.explanation] == ["candidate"]


def test_other_kind_is_not_covered_and_nobody_is_named() -> None:
    result = run([grant(DIRECTOR, "contract")], kind="letter_out")
    assert not result.resolved and result.candidates == []
    assert [s.code for s in result.explanation] == ["no_authority"]


def test_period_is_inclusive_on_both_ends() -> None:
    held = [grant(DIRECTOR, start=DAY, end=DAY)]
    assert ids(run(held)) == [DIRECTOR]
    assert reasons(run(held, on=date(2026, 11, 11))) == {DIRECTOR: "expired"}
    assert reasons(run(held, on=date(2026, 11, 9))) == {DIRECTOR: "not_started"}


def test_revoked_authority_is_refused_with_reason() -> None:
    result = run([grant(DIRECTOR, revoked=True)])
    assert not result.resolved and reasons(result) == {DIRECTOR: "revoked"}
    assert "отозвано" in result.rejected[0].message
    assert [s.code for s in result.explanation] == ["revoked", "no_signer"]


def test_charter_without_end_never_expires() -> None:
    assert ids(run([grant(DIRECTOR)], on=date(2040, 1, 1))) == [DIRECTOR]


def test_deactivated_owner_loses_the_authority() -> None:
    staff = people(u3=Holder(DIRECTOR, "Рустам Директоров", "Директор", False))
    result = run([grant(DIRECTOR)], staff=staff)
    assert not result.resolved and reasons(result) == {DIRECTOR: "holder_inactive"}


def test_owner_missing_from_projection_is_not_a_signer() -> None:
    result = run([grant(99)])
    assert not result.resolved and reasons(result) == {99: "holder_inactive"}
    assert result.rejected[0].signer.full_name == "Сотрудник #99"


# --- лимит и валюта --------------------------------------------------------------------------------------------------


def test_limit_allows_up_to_and_including_the_limit() -> None:
    held = [poa(CLERK, limit="10000000.00", currency="UZS")]
    assert ids(run(held, amount="10000000.00", currency="UZS")) == [CLERK]
    over = run(held, amount="10000000.01", currency="UZS")
    assert reasons(over) == {CLERK: "limit_exceeded"} and "10 000 000.00 UZS" in over.rejected[0].message


def test_document_without_amount_skips_the_limit() -> None:
    assert ids(run([poa(CLERK, limit="1.00", currency="UZS")])) == [CLERK]


def test_amount_in_another_currency_is_not_converted() -> None:
    held = [poa(CLERK, limit="10000000.00", currency="UZS")]
    result = run(held, amount="100.00", currency="USD")
    assert not result.resolved and reasons(result) == {CLERK: "currency_mismatch"}


def test_unlimited_authority_signs_any_amount_in_any_currency() -> None:
    assert ids(run([grant(DIRECTOR)], amount="999999999.00", currency="USD")) == [DIRECTOR]


def test_second_authority_of_the_same_person_covers_the_amount() -> None:
    small = poa(CLERK, limit="1000000.00", currency="UZS", number="1")
    large = poa(CLERK, limit="50000000.00", currency="UZS", number="2")
    result = run([small, large], amount="20000000.00", currency="UZS")
    assert ids(result) == [CLERK] and result.candidates[0].authority.basis_number == "2"
    assert reasons(result) == {}  # лимит первой не мешает: есть подходящая вторая


def test_overlapping_charter_and_power_of_attorney_give_one_candidate_charter_first() -> None:
    result = run([poa(DIRECTOR), grant(DIRECTOR)])
    assert ids(result) == [DIRECTOR]
    assert [a.basis for a in result.candidates[0].authorities] == ["charter", "power_of_attorney"]
    assert result.candidates[0].basis_text is None


def test_power_of_attorney_candidate_carries_the_basis_text() -> None:
    result = run([poa(CLERK)])
    assert result.candidates[0].basis_text == "Действует по доверенности № 17 от 01.03.2026 (до 01.03.2027)"


def test_basis_text_formulas() -> None:
    assert basis_text("charter", None, None, None) is None
    assert basis_text("order", "12-к", date(2026, 5, 4), None) == "Действует на основании приказа № 12-к от 04.05.2026"


def test_candidates_are_ordered_charter_then_order_then_power_of_attorney_then_name() -> None:
    order = grant(MANAGER, basis="order", number="5", issued=date(2026, 2, 1))
    result = run([poa(CLERK), order, grant(DEPUTY), grant(DIRECTOR)])
    assert ids(result) == [DEPUTY, DIRECTOR, MANAGER, CLERK]


# --- замещение: переводит задачу, прав не даёт -----------------------------------------------------------------------


def absent(start: date = date(2026, 11, 9), end: date = date(2026, 11, 20), deputy: int = DEPUTY) -> dict[int, Holder]:
    return people(u3=Holder(DIRECTOR, "Рустам Директоров", "Директор", True, deputy, start, end))


def test_absent_director_task_goes_to_deputy_who_has_own_authority() -> None:
    held = [grant(DIRECTOR), poa(DEPUTY, number="9")]
    result = run(held, staff=absent())
    assert ids(result) == [DEPUTY]
    candidate = result.candidates[0]
    assert [p.crm_user_id for p in candidate.acting_for] == [DIRECTOR]
    assert candidate.authority.basis == "power_of_attorney"
    assert reasons(result) == {DIRECTOR: "absent"}
    assert [s.code for s in result.explanation] == ["absent", "candidate_deputy"]
    assert "Дилшод Замов" in result.explanation[0].text and "по 20.11.2026" in result.explanation[0].text


def test_deputy_without_own_authority_cannot_sign_and_the_absent_one_cannot_either() -> None:
    result = run([grant(DIRECTOR)], staff=absent())
    assert not result.resolved
    assert reasons(result) == {DIRECTOR: "absent", DEPUTY: "deputy_without_authority"}
    assert "замещение прав не даёт" in result.explanation[1].text
    assert [s.code for s in result.explanation] == ["absent", "deputy_without_authority", "no_signer"]


def test_deputy_authority_limited_below_the_amount_does_not_help() -> None:
    held = [grant(DIRECTOR), poa(DEPUTY, limit="1000000.00", currency="UZS")]
    result = run(held, amount="5000000.00", currency="UZS", staff=absent())
    assert not result.resolved
    assert [r.reason for r in result.rejected if r.signer.crm_user_id == DEPUTY] == [
        "limit_exceeded",
        "deputy_without_authority",
    ]
    assert reasons(result)[DIRECTOR] == "absent"


def test_deputy_authority_of_another_kind_does_not_help() -> None:
    held = [grant(DIRECTOR, "contract"), grant(DEPUTY, "letter_out")]
    result = run(held, kind="contract", staff=absent())
    assert not result.resolved and reasons(result) == {DIRECTOR: "absent", DEPUTY: "deputy_without_authority"}


def test_substitution_period_is_inclusive_and_outside_it_the_holder_signs() -> None:
    held = [grant(DIRECTOR), grant(DEPUTY)]
    assert ids(run(held, staff=absent(), on=date(2026, 11, 9))) == [DEPUTY]
    assert ids(run(held, staff=absent(), on=date(2026, 11, 20))) == [DEPUTY]
    assert ids(run(held, staff=absent(), on=date(2026, 11, 8))) == [DEPUTY, DIRECTOR]
    assert ids(run(held, staff=absent(), on=date(2026, 11, 21))) == [DEPUTY, DIRECTOR]


def test_deputy_is_listed_first_with_the_names_he_acts_for() -> None:
    result = run([grant(DIRECTOR), grant(DEPUTY), grant(CLERK)], staff=absent())
    assert ids(result) == [DEPUTY, CLERK]
    assert [p.crm_user_id for p in result.candidates[0].acting_for] == [DIRECTOR]
    assert result.candidates[1].acting_for == []


def test_chain_of_deputies_reaches_the_first_present_person() -> None:
    staff = absent(deputy=DEPUTY)
    staff[DEPUTY] = Holder(DEPUTY, "Дилшод Замов", "Заместитель", True, CLERK, date(2026, 11, 9), date(2026, 11, 20))
    result = run([grant(DIRECTOR), poa(CLERK)], staff=staff)
    assert ids(result) == [CLERK] and [p.crm_user_id for p in result.candidates[0].acting_for] == [DIRECTOR]


def test_loop_of_deputies_is_refused() -> None:
    staff = absent()
    staff[DEPUTY] = Holder(DEPUTY, "Дилшод Замов", "Заместитель", True, DIRECTOR, date(2026, 11, 9), date(2026, 11, 20))
    result = run([grant(DIRECTOR)], staff=staff)
    assert not result.resolved and reasons(result) == {DIRECTOR: "deputy_loop"}


def test_deactivated_deputy_cannot_receive_the_task() -> None:
    staff = absent()
    staff[DEPUTY] = Holder(DEPUTY, "Дилшод Замов", "Заместитель", False)
    result = run([grant(DIRECTOR), grant(DEPUTY)], staff=staff)
    assert not result.resolved and reasons(result)[DEPUTY] in {"holder_inactive", "deputy_without_authority"}


# --- «может ли подписать этот сотрудник» -----------------------------------------------------------------------------


def test_signer_check_allows_a_candidate_and_explains_every_refusal() -> None:
    result = run([grant(DIRECTOR), grant(DEPUTY, number=None)], staff=absent())
    assert signer_check(result, DEPUTY).allowed
    absent_one = signer_check(result, DIRECTOR)
    assert not absent_one.allowed and absent_one.reason == "absent" and "Дилшод Замов" in absent_one.message
    stranger = signer_check(result, MANAGER)
    assert not stranger.allowed and stranger.reason == "no_authority" and "Права подписи" in stranger.message


def test_amount_is_reported_with_two_decimals() -> None:
    result = run([grant(DIRECTOR)], amount="5", currency="UZS")
    assert result.amount == "5.00" and result.currency == "UZS" and result.on_date == DAY
