"""Акт печатается по ШАБЛОНУ, а не из кода (spec-editable-outgoing-documents, E1).

Возражение юриста контрагента по формулировке — обычный ход сделки, и продавец должен уметь на
него ответить. Эталоны дают это право через редактирование ШАБЛОНА, а не произвольных строк:
структурные блоки вставляются одним плейсхолдером и собираются сервером (аналог locked block у
PandaDoc), текст вокруг них компания пишет сама.

Главный инвариант — обратная совместимость: компания без своего шаблона печатает платформенный
образец, который дословно повторяет прежний документ.
"""

import pytest

from crm.models import DocumentTemplate, DocumentTemplateKind
from crm.services.document_blocks import DOCUMENT_BLOCKS, company_template_for, render_document_body


@pytest.mark.django_db
def test_platform_sample_exists_for_the_act_after_migrate():
    """Rule 1: заготовка приходит миграцией — на чистой базе она уже есть."""
    sample = company_template_for(None, "ACT")

    assert sample is not None
    assert sample.is_sample is True and sample.company_id is None
    assert "Настоящий Акт составлен" in sample.body_html, "образец повторяет прежний текст"


@pytest.mark.django_db
def test_company_template_wins_over_the_platform_sample(db):
    """Своё важнее общего — иначе правка компании не доехала бы до документа."""
    from accounts.models import Company

    company = Company.objects.create(name="Своя компания", inn="9001000001")
    DocumentTemplate.objects.create(
        company=company,
        kind=DocumentTemplateKind.objects.get(code="ACT"),
        name="Наш акт",
        body_html="<p>Наша редакция</p>",
        is_active=True,
    )

    chosen = company_template_for(company, "ACT")

    assert chosen.company_id == company.id and chosen.name == "Наш акт"


@pytest.mark.django_db
def test_inactive_company_template_falls_back_to_the_sample(db):
    """Выключенный шаблон не должен молча ломать печать документа."""
    from accounts.models import Company

    company = Company.objects.create(name="Выключено", inn="9001000002")
    DocumentTemplate.objects.create(
        company=company,
        kind=DocumentTemplateKind.objects.get(code="ACT"),
        name="Черновик",
        body_html="<p>Не готово</p>",
        is_active=False,
    )

    chosen = company_template_for(company, "ACT")

    assert chosen.is_sample is True


def test_blocks_are_inserted_as_markup_and_scalars_are_escaped():
    """Разница блока и скаляра — про безопасность, а не про удобство."""
    body = "<p>{{doc.number}}</p>{{doc.items_table}}"

    out = render_document_body(
        body,
        blocks={"doc.items_table": "<table><tr><td>строка</td></tr></table>"},
        scalars={"doc.number": "<b>ACT-1</b>"},
    )

    assert "<table><tr><td>строка</td></tr></table>" in out, "блок — уже разметка сервера"
    assert "&lt;b&gt;ACT-1&lt;/b&gt;" in out, "значение данных обязано экранироваться"


def test_unknown_placeholder_is_left_verbatim():
    """Опечатка в шаблоне не должна молча съедать кусок документа."""
    out = render_document_body("{{doc.nonexistent}}", blocks={}, scalars={})

    assert out == "{{doc.nonexistent}}"


def test_template_body_is_never_executed_as_a_django_template():
    """Подстановка строковая: конструкция шаблонизатора внутри тела остаётся текстом (нет SSTI)."""
    out = render_document_body("{% raw %}{{ 7|add:7 }}{% endraw %}", blocks={}, scalars={})

    assert "14" not in out


def test_block_catalogue_covers_every_structural_part_of_the_legal_documents():
    """Каталог блоков один: и редактор показывает его пользователю, и проверка целостности (E2)
    сверяется с ним — разъехаться они не могут. E1b: к блокам акта добавились блоки счёта
    (платёжные реквизиты) и договора (спецификация, реквизиты и подписи), подписи и примечание."""
    assert set(DOCUMENT_BLOCKS) == {
        "doc.refs",
        "doc.items_table",
        "doc.totals",
        "doc.signatures",
        "doc.payment_requisites",
        "doc.spec_table",
        "doc.requisites_and_signatures",
        "doc.notes",
        "doc.extra_terms_article",
    }
