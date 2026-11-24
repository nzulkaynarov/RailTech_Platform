from app.domain.lead_repeat import compare_contacts, is_customer_form


def test_compare_contacts_fills_empty_and_keeps_differing() -> None:
    result = compare_contacts(
        {"email": None, "phone_e164": "+998901234567", "company_name": "A"},
        {"email": "x@y.uz", "phone_e164": "+998901234567", "company_name": "B"},
    )
    assert result.filled == {"email": "x@y.uz"}
    assert result.differing == {"company_name": "B"}


def test_compare_is_case_insensitive_and_ignores_empty_incoming() -> None:
    result = compare_contacts({"email": "x@y.uz"}, {"email": "X@Y.uz", "company_name": " "})
    assert (result.filled, result.differing) == ({}, {})


def test_customer_form() -> None:
    assert is_customer_form(None)
    assert is_customer_form("site-customer")
    assert not is_customer_form("site-partner")
