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

from accounts.services.bank_accounts import set_uzs_account
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
    seller.bank_accounts.all().delete()

    result, err = issue_invoice(invoice, world["seller_user"])

    assert result is None
    assert err == "SELLER_BANK_DETAILS_REQUIRED"
    invoice.refresh_from_db()
    assert invoice.status_code == "DRAFT", "счёт не должен выйти в ISSUED без реквизитов"


@pytest.mark.django_db
def test_issue_freezes_bank_details_snapshot(draft_invoice):
    world, invoice = draft_invoice
    seller = _ready_seller(world)  # СЦ-3: продавец с ИНН и адресом — иначе счёт не выйти

    result, err = issue_invoice(invoice, world["seller_user"])
    assert err is None, err

    result.refresh_from_db()
    assert "2020 8000 9000 0123 4567" in result.frozen_bank_details
    assert "00443" in result.frozen_bank_details

    # Смена банка ПОСЛЕ выставления не переписывает уже выпущенный документ.
    set_uzs_account(seller, "20208000999999999999", "00443")
    result.refresh_from_db()
    assert "2020 8000 9000 0123 4567" in result.frozen_bank_details


# ── СЦ-3: ИНН и юридический адрес продавца тоже нужны ──────────────────────────────────────────────────────────────


def _ready_seller(world):
    seller = _seller_company(world)
    set_uzs_account(seller, "20208000900001234567", "00443")
    seller.inn = seller.inn or "301234567"
    seller.legal_address = seller.legal_address or "г. Ташкент, ул. Демо, 1"
    seller.save(update_fields=["inn", "legal_address"])
    return seller


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["inn", "legal_address"])
def test_issue_blocked_without_seller_inn_or_address(draft_invoice, missing):
    from accounts.models import CompanyDocumentProfile
    from crm.services.invoice_lifecycle import invoice_bank_details_ready

    world, invoice = draft_invoice
    seller = _ready_seller(world)
    CompanyDocumentProfile.objects.filter(company=seller).update(**{missing: ""})
    setattr(seller, missing, "")
    seller.save(update_fields=[missing])

    assert invoice_bank_details_ready(invoice) is False
    result, err = issue_invoice(invoice, world["seller_user"])

    assert (result, err) == (None, "SELLER_BANK_DETAILS_REQUIRED")


@pytest.mark.django_db
def test_inn_from_the_letterhead_profile_is_enough(draft_invoice):
    """Печать берёт ИНН из бланка, если в карточке пусто — гейт считает так же."""
    from accounts.models import CompanyDocumentProfile

    world, invoice = draft_invoice
    seller = _ready_seller(world)
    CompanyDocumentProfile.objects.update_or_create(company=seller, defaults={"inn": "301234567"})
    seller.inn = ""
    seller.save(update_fields=["inn"])

    result, err = issue_invoice(invoice, world["seller_user"])

    assert err is None, err
