"""Счёт нельзя выставить без банковских реквизитов, а выставленный печатает их СНИМОК (O3).

Наблюдение из прогона глазами 17-08: PDF счёта выходил с блоком «Платёжные реквизиты», где
есть получатель и назначение платежа, но нет расчётного счёта — заплатить по такому документу
нельзя, и продавца никто не предупредил.

Эталоны: Odoo держит счёт получателя ПОЛЕМ НА ДОКУМЕНТЕ («Recipient Bank») и блокирует
проведение с внятной ошибкой-ссылкой в настройки (RedirectWarning); HubSpot не пускает счёт
из draft в open, пока нет «всех деталей, необходимых для отправки покупателю». Гейт стоит
только на выпуске счёта — КП и договор он не трогает.
"""

import pytest

from crm.services.invoice_lifecycle import issue_invoice
from crm.tests.test_act_two_sided import act_world, lookups  # noqa: F401


@pytest.fixture
def draft_invoice(act_world):  # noqa: F811
    """Черновик счёта той же сделки — акт из мира нам не мешает."""
    from crm.constants import InvoiceStatusCode
    from crm.models import Invoice, InvoiceStatus

    world = act_world
    invoice = world["invoice"]
    invoice.status = InvoiceStatus.objects.get(code=InvoiceStatusCode.DRAFT)
    invoice.issued_at = None
    invoice.save(update_fields=["status", "issued_at"])
    return world, Invoice.objects.get(pk=invoice.pk)


def _seller_company(world):
    """Продавец счёта — ровно тот, кого резолвит сам сервис (одна правда с гейтом)."""
    from crm.services.billing import _invoice_seller_company

    seller = _invoice_seller_company(world["invoice"])
    assert seller is not None, "мир теста не даёт продавца счёта"
    return seller


@pytest.mark.django_db
def test_issue_blocked_without_bank_details(draft_invoice):
    world, invoice = draft_invoice
    seller = _seller_company(world)
    seller.bank_account = ""
    seller.mfo = ""
    seller.save(update_fields=["bank_account", "mfo"])

    result, err = issue_invoice(invoice, world["seller_user"])

    assert result is None
    assert err == "SELLER_BANK_DETAILS_REQUIRED"
    invoice.refresh_from_db()
    assert invoice.status_code == "DRAFT", "счёт не должен выйти в ISSUED без реквизитов"


@pytest.mark.django_db
def test_issue_freezes_bank_details_snapshot(draft_invoice):
    world, invoice = draft_invoice
    seller = _seller_company(world)
    seller.bank_account = "20208000900001234567"
    seller.mfo = "00443"
    seller.save(update_fields=["bank_account", "mfo"])

    result, err = issue_invoice(invoice, world["seller_user"])
    assert err is None, err

    result.refresh_from_db()
    assert "20208000900001234567" in result.frozen_bank_details
    assert "00443" in result.frozen_bank_details

    # Смена банка ПОСЛЕ выставления не переписывает уже выпущенный документ.
    seller.bank_account = "99999999999999999999"
    seller.save(update_fields=["bank_account"])
    result.refresh_from_db()
    assert "20208000900001234567" in result.frozen_bank_details
