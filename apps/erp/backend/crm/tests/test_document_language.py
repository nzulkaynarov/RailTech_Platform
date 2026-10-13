"""M1 — закрывающие документы на языке получателя (spec-documents-recipient-language).

Канон Stripe: PDF счёта/квитанции локализуется по языку ПОКУПАТЕЛЯ, при этом переводится
КАРКАС (лейблы, итоги, подписи), а содержание — позиции, формулировки, названия компаний —
остаётся языком автора. Тесты держат обе половины этого контракта.
"""

from decimal import Decimal

import pytest
from django.utils import translation

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage
from crm.services.document_blocks import document_recipient_language
from crm.services.money_words import money_in_words, money_in_words_en


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _buyer_with_languages(languages, inn):
    company = Company.objects.create(name=f"Buyer {inn}", inn=inn)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    for index, language in enumerate(languages):
        user = CustomUser.objects.create_user(
            email=f"u{index}@{inn}.test",
            username=f"u{index}@{inn}.test",
            password="x",
            preferences={"language": language},
        )
        CompanyMember.objects.create(
            user=user,
            company=company,
            role=WorkspaceRole.objects.get(code="OWNER"),
            is_active=True,
            is_primary=index == 0,
        )
    return company


@pytest.mark.django_db
def test_document_language_follows_the_buyer(lookups):
    """Продавец печатает — покупатель читает. Язык берётся у стороны-получателя."""
    company = _buyer_with_languages(["en", "en"], "9930000001")
    deal = Deal.objects.create(title="EN buyer", company=company, stage=DealStage.objects.get(code="DRAFT"))

    with translation.override("ru"):  # продавец работает по-русски
        assert document_recipient_language(deal) == "en"


@pytest.mark.django_db
def test_mixed_team_falls_back_to_platform_language(lookups):
    """Документ ОДИН на всю сторону: если команда покупателя говорит на разных языках,
    выбирать чей-то личный было бы произволом — печатаем на языке платформы."""
    company = _buyer_with_languages(["en", "ru"], "9930000002")
    deal = Deal.objects.create(title="Mixed", company=company, stage=DealStage.objects.get(code="DRAFT"))

    assert document_recipient_language(deal) == "ru"


@pytest.mark.django_db
def test_solo_deal_without_buyer_company_uses_platform_language(lookups):
    """Соло-сделка (Deal.company пуст) языка не сообщает."""
    deal = Deal.objects.create(title="Solo", stage=DealStage.objects.get(code="DRAFT"))

    assert document_recipient_language(deal) == "ru"
    assert document_recipient_language(None) == "ru"


class TestAmountInWordsEnglish:
    """Пропись — денежный реквизит: проверяем на краевых случаях, а не «на глазок»."""

    def test_matches_russian_engine_contract(self):
        for junk in (None, "", "не число"):
            assert money_in_words_en(junk) == "—" == money_in_words(junk)

    def test_singular_and_plural_forms(self):
        assert money_in_words_en("1.01", "UZS") == "One soum 01 tiyin"
        assert money_in_words_en("2.00", "USD") == "Two dollars 00 cents"
        assert money_in_words_en("1.01", "USD") == "One dollar 01 cent"

    def test_hyphenated_tens_and_scales(self):
        assert money_in_words_en("42.00", "USD").startswith("Forty-two dollars")
        assert money_in_words_en("12500000.50", "UZS") == "Twelve million five hundred thousand soums 50 tiyin"

    def test_zero_and_negative(self):
        assert money_in_words_en("0.00", "UZS").startswith("Zero")
        assert money_in_words_en("-345.25", "UZS").startswith("minus Three hundred forty-five")

    def test_unknown_currency_never_claims_a_wrong_word(self):
        """Как и русский движок: неизвестный код печатается кодом, а не чужой валютой."""
        phrase = money_in_words_en("10.00", "CNY")
        assert "soum" not in phrase and "dollar" not in phrase
        assert "CNY" in phrase


@pytest.mark.django_db
def test_amount_in_words_filter_follows_document_language():
    """Фильтр обязан следовать активному языку документа, иначе в английском акте посреди
    страницы стояла бы русская пропись."""
    from crm.templatetags.document_format import money_words

    with translation.override("en"):
        assert money_words(Decimal("1.01"), "UZS") == "One soum 01 tiyin"
    with translation.override("ru"):
        assert money_words(Decimal("1.01"), "UZS") == "Один сум 01 тийин"
