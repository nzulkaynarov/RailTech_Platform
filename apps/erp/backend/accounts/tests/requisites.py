"""Продавец, готовый выставлять счета (СЦ-3): расчётный счёт в сумах, ИНН и юридический адрес — без них гейт выпуска
счёта откажет `SELLER_BANK_DETAILS_REQUIRED`. Пустые ИНН и адрес не перетираются заполненными."""

from accounts.services.bank_accounts import set_uzs_account


def ready_for_invoices(company, account: str = "20208000900001234567", mfo: str = "00443"):
    set_uzs_account(company, account, mfo)
    changed = []
    if not (company.inn or "").strip():
        company.inn = "301234567"
        changed.append("inn")
    if not (company.legal_address or "").strip():
        company.legal_address = "г. Ташкент, ул. Тестовая, 1"
        changed.append("legal_address")
    if changed:
        company.save(update_fields=changed)
    return company
