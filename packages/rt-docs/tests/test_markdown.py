"""План 1.3: мост Markdown ↔ тело документа — черновик помощника становится телом и обратно."""

from __future__ import annotations

from rt_docs import body_to_markdown, load_catalog, markdown_to_body, validate_body

DRAFT = """# Коммерческое предложение

Уважаемый {{recipient.name}}!

Предлагаем **поставку** стрелочных переводов *в срок*:

- перевод Р65 1/11 — 2 шт.;
- монтаж и [пусконаладка](https://railtech.uz/services).

1. Предоплата 50%.
2. Остаток после поставки.

| Позиция | Кол-во | Ед. |
| --- | --- | --- |
| Перевод Р65 | 2 | компл. |
| Шпала | 300 | шт. |

{{doc.signature_block}}
"""


def test_assistant_draft_becomes_a_valid_body() -> None:
    result = markdown_to_body(DRAFT, catalog=load_catalog())
    validate_body(result.body)
    blocks = result.body["doc"]["content"]
    assert [b["type"] for b in blocks] == [
        "heading",
        "paragraph",
        "paragraph",
        "bulletList",
        "orderedList",
        "table",
        "block",
    ]
    greeting = blocks[1]["content"]
    assert {"type": "variable", "attrs": {"code": "recipient.name"}} in greeting
    offer = blocks[2]["content"]
    assert {"type": "text", "text": "поставку", "marks": [{"type": "bold"}]} in offer
    table = blocks[5]["content"]
    assert [cell["type"] for cell in table[0]["content"]] == ["tableHeader"] * 3
    assert blocks[6]["attrs"]["code"] == "doc.signature_block"


def test_body_returns_to_the_same_markdown() -> None:
    body = markdown_to_body(DRAFT, catalog=load_catalog()).body
    markdown = body_to_markdown(body)
    assert markdown == DRAFT
    again = markdown_to_body(markdown, catalog=load_catalog()).body
    assert again == body, "Markdown → тело → Markdown → тело — без потерь"


def test_raw_html_and_unsafe_links_stay_plain_text() -> None:
    """Сырой HTML выключен, небезопасная ссылка не становится ссылкой: всё это — обычный текст абзаца."""
    result = markdown_to_body("<script>alert(1)</script>\n\n[клик](javascript:alert(1)) и <b>жирный</b>")
    validate_body(result.body)
    inline = [n for block in result.body["doc"]["content"] for n in block.get("content", [])]
    assert all(n["type"] == "text" and "marks" not in n for n in inline), "ни ссылки, ни жирного из HTML"
    assert "<b>жирный</b>" in "".join(n["text"] for n in inline)
    assert markdown_to_body(body_to_markdown(result.body)).body == result.body


def test_special_characters_survive_the_round_trip() -> None:
    body = markdown_to_body("Скидка 5% на *всё* и пункт \\#3 с символом \\| в тексте.").body
    again = markdown_to_body(body_to_markdown(body)).body
    assert again == body


def test_empty_draft_is_an_empty_paragraph() -> None:
    result = markdown_to_body("")
    validate_body(result.body)
    assert body_to_markdown(result.body) == ""
