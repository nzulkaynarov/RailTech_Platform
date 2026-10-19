"""Формулировки документов должны СОХРАНЯТЬСЯ, а не пропадать с зелёным тостом.

Поля прозы договора и акта (`contract_acceptance_text`, `contract_liability_text`,
`contract_extra_terms_text`, `act_closing_text`) появились миграцией accounts/0043, объявлены
в сериализаторе профиля и читаются печатью (`crm/document_wording.py`), но в whitelist сервиса
записи не попали. Итог: PATCH возвращал 200, интерфейс показывал «Профиль документов сохранён»,
а значение оставалось пустым — задать прозу договора из интерфейса было нельзя вовсе.
Найдено прогоном глазами 19-08; тесты D1 это не ловили, потому что проверяли ПЕЧАТЬ при уже
заполненном поле, а не путь сохранения.

Второй тест держит связку двух списков: набор настраиваемых формулировок объявлен в
`DOCUMENT_WORDING_DEFAULTS`, и каждый его ключ обязан быть записываемым. Именно это
рассогласование («расширили в одном месте, забыли в другом») и было корнем.
"""

import pytest

from accounts.models import Company, CompanyDocumentProfile, CompanyMember, CustomUser, WorkspaceRole
from accounts.services.document_profile import _EDITABLE_FIELDS, update_document_profile
from accounts.testing import grant_head, make_own_company
from crm.document_wording import DOCUMENT_WORDING_DEFAULTS


@pytest.fixture
def company(db):
    return make_own_company(Company.objects.create(name="ООО Пример", inn="300000123"))


@pytest.fixture
def owner(db, company):
    """Формулировки правит владелец компании — сервис отказывает всем остальным."""
    user = CustomUser.objects.create_user(
        email="owner@example.uz", username="owner_wording", password="pw", is_active=True
    )
    role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "OWNER", "sort_order": 10})
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True)
    grant_head(user, company)
    return user


@pytest.mark.django_db
def test_wording_texts_are_saved(owner, company):
    profile, _ = CompanyDocumentProfile.objects.get_or_create(company=company)
    update_document_profile(
        owner,
        company,
        {
            "contract_acceptance_text": "Приёмка по количеству и качеству — 5 рабочих дней.",
            "act_closing_text": "Работы выполнены полностью, претензий нет.",
        },
    )
    profile.refresh_from_db()
    assert profile.contract_acceptance_text == "Приёмка по количеству и качеству — 5 рабочих дней."
    assert profile.act_closing_text == "Работы выполнены полностью, претензий нет."


@pytest.mark.django_db
def test_every_configurable_wording_is_writable():
    """Список настраиваемых формулировок и список записываемых полей не должны расходиться."""
    missing = sorted(set(DOCUMENT_WORDING_DEFAULTS) - set(_EDITABLE_FIELDS))
    assert not missing, (
        "формулировки объявлены настраиваемыми, но сервис их не пишет — "
        f"интерфейс будет врать «сохранено»: {missing}"
    )


@pytest.mark.django_db
def test_clearing_wording_returns_to_platform_default(owner, company):
    """Пустое поле означает «печатать платформенную формулировку», а не «печатать пустоту»."""
    profile, _ = CompanyDocumentProfile.objects.get_or_create(company=company)
    update_document_profile(owner, company, {"contract_acceptance_text": "Своя приёмка"})
    profile.refresh_from_db()
    assert profile.contract_acceptance_text == "Своя приёмка"

    update_document_profile(owner, company, {"contract_acceptance_text": ""})
    profile.refresh_from_db()
    assert profile.contract_acceptance_text == ""
