"""ДК-5: сообщение бота о документе партнёра-поставщика — вид, номер и отправитель."""

import pytest
from rt_contracts.events.erp import DocumentKind

from app.domain import client_texts


@pytest.mark.parametrize("language", ["ru", "uz", "en"])
@pytest.mark.parametrize("kind", ["price_request", "supplier_order"])
def test_partner_document_kinds_have_text_in_every_language(kind: str, language: str) -> None:
    text = client_texts.document_link_message(language, kind, "ЗП-2026-031", "ООО Покупатель")
    assert "ЗП-2026-031" in text
    assert "ООО Покупатель" in text


def test_every_event_document_kind_has_a_text() -> None:
    for kind in DocumentKind:
        assert client_texts.document_link_message("ru", kind.value, "1", None)


def test_uzbek_uses_the_new_alphabet() -> None:
    text = client_texts.document_link_message("uz", "price_request", "1", None)
    assert "Narx sörovi" in text
    assert "o‘" not in text
    assert "oʻ" not in text
