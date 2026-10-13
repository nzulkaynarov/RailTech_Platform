"""Формулировки документов стали данными, но документ без настроек не изменился.

Граница «код / данные» проведена по эталону отчётов (Odoo QWeb: настраиваемый текст живёт в полях
модели, структура — в шаблоне): проза договора и акта редактируется компанией, каркас нет.

Главный инвариант здесь — **обратная совместимость**: компания, которая ничего не настраивала,
обязана получить ровно тот документ, что и раньше. Пустое поле означает «печатать платформенную
формулировку», а не «печатать пусто» — иначе внедрение настроек молча выпотрошило бы договоры.
"""

import pytest

from crm.document_wording import (
    DEFAULT_ACT_CLOSING,
    DEFAULT_CONTRACT_ACCEPTANCE,
    DEFAULT_CONTRACT_LIABILITY,
    DOCUMENT_WORDING_DEFAULTS,
    document_wording_context,
    resolve_wording,
)


class _Profile:
    """Минимальный носитель полей — сервис читает их через getattr, модель не нужна."""

    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


def test_empty_profile_prints_the_platform_wording():
    """Ничего не настраивали — документ прежний."""
    assert resolve_wording(_Profile(contract_acceptance_text=""), "contract_acceptance_text") == (
        DEFAULT_CONTRACT_ACCEPTANCE
    )
    assert resolve_wording(None, "contract_liability_text") == DEFAULT_CONTRACT_LIABILITY
    assert resolve_wording(None, "act_closing_text") == DEFAULT_ACT_CLOSING


def test_company_wording_replaces_the_platform_one():
    profile = _Profile(contract_liability_text="Неустойка 0,05% за каждый день просрочки.")

    assert resolve_wording(profile, "contract_liability_text") == "Неустойка 0,05% за каждый день просрочки."


def test_whitespace_only_is_treated_as_not_configured():
    """Пробелы — это не формулировка: договор не должен остаться с пустым пунктом."""
    assert resolve_wording(_Profile(act_closing_text="   \n  "), "act_closing_text") == DEFAULT_ACT_CLOSING


def test_extra_terms_default_is_empty_so_the_clause_stays_hidden():
    """Особые условия печатаются, ТОЛЬКО если их написали: пустой пункт хуже отсутствующего."""
    assert DOCUMENT_WORDING_DEFAULTS["contract_extra_terms_text"] == ""
    assert resolve_wording(None, "contract_extra_terms_text") == ""


def test_tokens_are_substituted_flatly_and_never_rendered_as_a_template():
    """Подстановка строковая: шаблонная конструкция внутри текста остаётся текстом (нет SSTI)."""
    profile = _Profile(act_closing_text="Принято {{buyer}}. {% raw %}{{ 7*7 }}{% endraw %}")

    out = resolve_wording(profile, "act_closing_text", buyer="ООО Ромашка")

    assert "ООО Ромашка" in out
    assert "49" not in out, "текст не должен исполняться как шаблон"


def test_context_covers_every_configurable_field():
    """Список настраиваемых формулировок один: расширить его в одном месте и забыть в другом нельзя."""
    context = document_wording_context(None)

    assert set(context) == {f"wording_{field}" for field in DOCUMENT_WORDING_DEFAULTS}


@pytest.mark.django_db
def test_contract_pdf_prints_the_company_wording(monkeypatch):
    """Сквозная проверка: то, что написала компания, доезжает до HTML документа."""
    from django.template.loader import render_to_string

    from crm.document_wording import document_wording_context

    profile = _Profile(
        contract_acceptance_text="Приёмка в течение 3 рабочих дней.",
        contract_liability_text="Неустойка 0,05%.",
        contract_extra_terms_text="Тара возвратная.",
        act_closing_text="",
    )
    html = render_to_string(
        "crm/contract_pdf.html",
        {
            "contract": None,
            "deal": None,
            "company": None,
            "quote": None,
            "totals": {},
            "items": [],
            **document_wording_context(profile),
        },
    )

    assert "Приёмка в течение 3 рабочих дней." in html
    assert "Неустойка 0,05%." in html
    assert "Особые условия" in html and "Тара возвратная." in html
    assert "11. Реквизиты и подписи Сторон" in html, "нумерация сдвигается вместе с особыми условиями"


@pytest.mark.django_db
def test_contract_pdf_without_settings_keeps_the_platform_text_and_numbering():
    from django.template.loader import render_to_string

    html = render_to_string(
        "crm/contract_pdf.html",
        {
            "contract": None,
            "deal": None,
            "company": None,
            "quote": None,
            "totals": {},
            "items": [],
            **document_wording_context(None),
        },
    )

    assert "виновная Сторона уплачивает неустойку в размере 0,1%" in html
    assert "Особые условия" not in html
    assert "10. Реквизиты и подписи Сторон" in html
