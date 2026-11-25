"""ДС-1: срок договора в BFF — настройки компании и карточка контрагента (перевод ответа ERP)."""

from app.api.people_contacts import to_contract_term
from app.schemas_company import QuoteDefaultsUpdate, to_quote_defaults


def test_quote_defaults_carry_the_term_rules_with_safe_fallbacks() -> None:
    raw = {
        "contract_term_rule": "twelve_months",
        "contract_notice_days": 14,
        "contract_expired_action": "warn",
    }
    defaults = to_quote_defaults(raw, ())
    assert (
        defaults.contract_term_rule,
        defaults.contract_notice_days,
        defaults.contract_expired_action,
    ) == (
        "twelve_months",
        14,
        "warn",
    )
    assert defaults.contract_auto_renew is True
    assert defaults.contract_remind_first_days == 30
    # ответ ERP до ДС-1 или с мусором — умолчания, а не 500
    fallback = to_quote_defaults(
        {"contract_term_rule": "forever", "contract_expired_action": 5}, ()
    )
    assert (fallback.contract_term_rule, fallback.contract_expired_action) == (
        "calendar_year",
        "block",
    )


def test_update_rejects_values_out_of_range() -> None:
    import pytest
    from pydantic import ValidationError

    assert QuoteDefaultsUpdate(contract_notice_days=0).contract_notice_days == 0
    for bad in (
        {"contract_notice_days": 366},
        {"contract_next_year_from_day": 0},
        {"contract_term_rule": "x"},
    ):
        with pytest.raises(ValidationError):
            QuoteDefaultsUpdate(**bad)


def test_counterparty_term_maps_and_tolerates_absence() -> None:
    term = to_contract_term(
        {
            "contract_id": 7,
            "number": "ДОГ-1",
            "state": "expired",
            "valid_until": "2025-12-31",
            "last_notice_date": None,
            "foreign": False,
            "blocks_new_work": True,
        }
    )
    assert term is not None
    assert (term.state, term.blocks_new_work) == ("expired", True)
    assert to_contract_term(None) is None
    assert to_contract_term({"state": "expired"}) is None
