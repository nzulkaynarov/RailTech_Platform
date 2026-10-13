import pytest
from docling_core.types.doc import DoclingDocument, TableCell, TableData
from docling_core.types.doc.labels import DocItemLabel

from app.services.kb.chunking import chunk_document, estimate_tokens


def table(rows: list[list[str]]) -> TableData:
    cells = [
        TableCell(
            text=value,
            start_row_offset_idx=r,
            end_row_offset_idx=r + 1,
            start_col_offset_idx=c,
            end_col_offset_idx=c + 1,
            column_header=r == 0,
        )
        for r, row in enumerate(rows)
        for c, value in enumerate(row)
    ]
    return TableData(num_rows=len(rows), num_cols=len(rows[0]), table_cells=cells)


@pytest.fixture
def document() -> DoclingDocument:
    doc = DoclingDocument(name="demo")
    doc.add_heading("Кассы RT-POS", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="RT-POS — онлайн-касса для розницы. " * 60)
    doc.add_heading("Тарифы", level=2)
    doc.add_table(
        data=table(
            [["Тариф", "Касс", "Цена"], ["Старт", "1", "150 000"], ["Сеть", "10", "1 200 000"]]
        )
    )
    return doc


def test_chunks_respect_limit_and_keep_headings(document: DoclingDocument) -> None:
    drafts = chunk_document(document, max_tokens=200)
    assert len(drafts) > 2
    assert all(d.token_count <= 200 for d in drafts)
    assert [d.position for d in drafts] == list(range(len(drafts)))
    assert drafts[0].heading_path == "Кассы RT-POS"
    assert drafts[-1].heading_path == "Кассы RT-POS > Тарифы"


def test_table_is_markdown(document: DoclingDocument) -> None:
    table_chunk = chunk_document(document, max_tokens=200)[-1]
    assert "| Тариф" in table_chunk.content
    assert "| Старт" in table_chunk.content
    assert "150 000" in table_chunk.content


def test_text_for_embedding_includes_headings(document: DoclingDocument) -> None:
    draft = chunk_document(document, max_tokens=200)[-1]
    assert draft.text_for_embedding.startswith("Кассы RT-POS > Тарифы\n")


def test_empty_document() -> None:
    assert chunk_document(DoclingDocument(name="empty")) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("касса", 2), ("a b c", 3), ("Цена?", 2), ("1234567890", 3)],
)
def test_estimate_tokens(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected
