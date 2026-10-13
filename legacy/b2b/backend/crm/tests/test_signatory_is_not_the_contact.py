"""Контактное лицо компании НЕ становится подписантом документов.

`Company.contact_person` отвечает на вопрос «с кем связаться», подписант — «кто подписывает».
В юридическом документе это разные роли, а правило #287 «Company authoritative» перекрывало
`signatory_name` контактом: в акте и квитанции печаталось «Подписант: System Admin» — контакт
демо-компании (проход глазами 03-08).

Эталон: у DocuSign и Adobe Sign подписант — отдельно назначаемая роль; у Odoo «Ответственный»
(`user_id`) не равен подписи компании.
"""

import pytest

from accounts.models import Company, CompanyDocumentProfile
from crm.services.documents.brand import document_brand_context

pytestmark = pytest.mark.django_db


def test_contact_person_never_becomes_the_signatory():
    company = Company.objects.create(
        name="ООО Продавец", inn="9000000001", contact_person="System Admin", legal_address="г. Ташкент"
    )
    CompanyDocumentProfile.objects.create(company=company, use_company_defaults=True)

    profile = document_brand_context(company)["seller_profile"]

    assert profile.signatory_name in ("", None), "контакт компании не должен подписывать документы"
    # Остальные поля правило #287 по-прежнему берёт из карточки компании.
    assert profile.legal_name == "ООО Продавец"
    assert profile.inn == "9000000001"


def test_explicit_signatory_from_the_document_profile_is_kept():
    company = Company.objects.create(name="ООО Продавец 2", inn="9000000002", contact_person="Менеджер Пупкин")
    CompanyDocumentProfile.objects.create(
        company=company,
        use_company_defaults=True,
        signatory_name="Каримов А.А.",
        signatory_position="Директор",
    )

    profile = document_brand_context(company)["seller_profile"]

    assert profile.signatory_name == "Каримов А.А."
    assert profile.signatory_position == "Директор"
