"""Подпись договора ставит перерисовку PDF в очередь (после коммита) — см. test_signed_pdf_rerender.py.
Отдельный файл: фикстуры мира берём из test_permission_guards (имя `lookups` там своё)."""

from unittest.mock import patch

import pytest

from crm.tests.test_permission_guards import (  # noqa: F401 — фикстуры мира
    _make_member,
    _make_user,
    _pending_client_contract,
    _sent_quote,
    buyer_company,
    deal,
    lookups,
    seller_company,
)


@pytest.mark.django_db
def test_contract_client_sign_enqueues_pdf_rerender(
    lookups, buyer_company, seller_company, deal, django_capture_on_commit_callbacks  # noqa: F811
):
    from crm.services.contracts import sign_contract_by_client

    seller = _make_user("rerender_seller@s.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)
    buyer = _make_user("rerender_buyer@b.test")
    _make_member(buyer, buyer_company, can_buy=True, is_primary=True)
    contract = _pending_client_contract(deal, quote)

    with patch("crm.tasks.render_document_pdf.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            result, err = sign_contract_by_client(contract.id, buyer)
    assert err is None, err
    assert ("contract", contract.id) in [call.args for call in delay.call_args_list]
