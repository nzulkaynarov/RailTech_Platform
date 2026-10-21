"""Встроенный конвертер Markdown/текста и выбор конвертера KB (M5-CRM-02)."""

import pytest
from pydantic import AnyHttpUrl

from app.config import Settings
from app.integrations.docling import DoclingClient, DoclingDisabledError
from app.services.kb.chunking import MAX_CHUNK_TOKENS, chunk_document
from app.services.kb.markdown_convert import (
    MarkdownConverter,
    is_markdown_file,
    markdown_to_document,
)

SAMPLE = """# Гарантия

Общий абзац
про срок.

## Условия

- один
- два
  продолжение

| Модель | Срок |
|---|---|
| А | 12 мес |
| Б | 24 мес |

### Глубже

1. первый
2. второй
"""


def test_headings_become_chunk_paths() -> None:
    drafts = chunk_document(markdown_to_document("a.md", SAMPLE))
    paths = [d.heading_path for d in drafts]
    assert paths == ["Гарантия", "Гарантия > Условия", "Гарантия > Условия > Глубже"]
    assert drafts[0].content == "Общий абзац про срок."
    assert "- два продолжение" in drafts[1].content
    assert drafts[2].content == "1. первый\n2. второй"


def test_table_keeps_rows_and_header() -> None:
    doc = markdown_to_document("a.md", SAMPLE)
    assert len(doc.tables) == 1
    assert (doc.tables[0].data.num_rows, doc.tables[0].data.num_cols) == (3, 2)
    content = chunk_document(doc)[1].content
    assert "| Модель" in content
    assert "| Б" in content
    assert "24 мес" in content


def test_empty_and_blank_files_give_no_chunks() -> None:
    assert chunk_document(markdown_to_document("e.md", "")) == []
    assert chunk_document(markdown_to_document("e.md", "\n  \n\n")) == []
    assert chunk_document(markdown_to_document("e.md", "#\n---\n")) == []


def test_paragraph_lines_and_code_fence() -> None:
    text = "Первая строка\nвторая.\n\n```py\nprint(1)\n```\n\nКонец"
    contents = [d.content for d in chunk_document(markdown_to_document("n.md", text))]
    assert len(contents) == 1
    assert "Первая строка вторая." in contents[0]
    assert "print(1)" in contents[0]
    assert contents[0].endswith("Конец")


def test_unclosed_fence_and_ragged_table_do_not_crash() -> None:
    chunk_document(markdown_to_document("a.md", "```\nкод без конца\n"))
    doc = markdown_to_document("a.md", "| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |\n")
    assert doc.tables[0].data.num_cols == 3


def test_large_file_is_split_within_limit() -> None:
    body = "\n\n".join(f"## Раздел {n}\n\n" + "Слово " * 400 for n in range(40))
    drafts = chunk_document(markdown_to_document("big.md", body))
    assert len(drafts) >= 40
    assert all(d.token_count <= MAX_CHUNK_TOKENS * 1.2 for d in drafts)
    assert drafts[0].heading_path == "Раздел 0"
    assert [d.position for d in drafts] == list(range(len(drafts)))


async def test_converter_decodes_bom_and_bad_bytes() -> None:
    doc = await MarkdownConverter().convert(
        "a.md", b"\xef\xbb\xbf# \xd0\x97\n\nok \xff", "text/markdown"
    )
    assert doc.texts[0].text == "З"
    assert "ok" in doc.texts[1].text


def test_is_markdown_file() -> None:
    assert is_markdown_file("Manual.MD")
    for name in ("notes.txt", "noext", "a.pdf", "a.html", "a.md.exe"):
        assert not is_markdown_file(name)


async def test_converter_strips_front_matter_and_rejects_other_formats() -> None:
    text = "---\ntitle: T\nlanguage: ru\n---\n# Заголовок\n\nТекст.\n"
    doc = await MarkdownConverter().convert("a.md", text.encode(), "text/markdown")
    assert [d.content for d in chunk_document(doc)] == ["Текст."]
    with pytest.raises(ValueError, match="only Markdown"):
        await MarkdownConverter().convert("a.pdf", b"%PDF", "application/pdf")


async def test_docling_client_without_url_fails_fast() -> None:
    settings = Settings(_env_file=None, docling_url=None)
    client = DoclingClient(settings)
    assert not client.enabled
    with pytest.raises(DoclingDisabledError):
        await client.convert("a.pdf", b"%PDF", "application/pdf")


def test_blank_docling_url_in_env_means_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCLING_URL", "")
    assert Settings(_env_file=None).docling_url is None
    monkeypatch.setenv("DOCLING_URL", "http://docling:5001")
    assert Settings(_env_file=None).docling_url == AnyHttpUrl("http://docling:5001")
