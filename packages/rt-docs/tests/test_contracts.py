"""Контракт documents: схема тела, примеры, каталог; эталоны тестов тоже проходят схему."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rt_docs import BodyError, ContractsNotFoundError, contracts_dir, load_catalog, validate_body
from tests import samples

EXAMPLES = sorted((contracts_dir() / "examples").glob("*.json"))


def test_contracts_dir_is_found_from_the_package_and_by_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert (contracts_dir() / "body.schema.json").is_file()
    monkeypatch.setenv("RT_DOCS_CONTRACTS_DIR", str(tmp_path))
    with pytest.raises(ContractsNotFoundError):
        contracts_dir()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_contract_examples_are_valid_bodies(path: Path) -> None:
    validate_body(json.loads(path.read_text(encoding="utf-8")))


def test_there_are_letter_contract_and_invoice_examples() -> None:
    assert {p.stem for p in EXAMPLES} >= {"letter", "letter.uz", "contract", "invoice"}


@pytest.mark.parametrize(
    "build",
    [
        samples.letter_short,
        samples.letter_uz,
        samples.contract,
        samples.invoice,
        samples.specification,
        lambda: samples.letter_paragraphs(8),
    ],
)
def test_reference_bodies_are_valid(build: Any) -> None:
    validate_body(build())


def test_items_tables_are_valid_block_data() -> None:
    validate_body(samples.body(samples.items_table(3) + samples.totals("—") + samples.payment_requisites()))


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (
            lambda b: b["doc"]["content"].append({"type": "paragraph", "content": [{"type": "html", "text": "<b>"}]}),
            "doc",
        ),
        (lambda b: b.update(lang="de"), "lang"),
        (lambda b: b["doc"]["content"].append({"type": "paragraph", "attrs": {"style": "color:red"}}), "doc"),
        (
            lambda b: b["doc"]["content"].append(
                samples.para(
                    {"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]}
                )
            ),
            "doc",
        ),
        (lambda b: b["doc"]["content"].append({"type": "paragraph", "content": [samples.var("Company Name")]}), "doc"),
        (lambda b: b.update(page={"tuning": {"lineHeight": 2.5}}), "page"),
        (lambda b: b.update(page={"font": "Comic Sans"}), "page"),
    ],
)
def test_schema_rejects_raw_html_styles_and_unsafe_links(mutate: Any, where: str) -> None:
    body = samples.letter_short()
    mutate(body)
    with pytest.raises(BodyError) as error:
        validate_body(body)
    assert any(p.startswith(where) for p in error.value.problems)


def test_catalog_has_labels_in_three_languages_and_required_blocks() -> None:
    catalog = load_catalog()
    assert catalog.label("counterparty.name", "uz") == "Kontragent — nomi"
    assert catalog.label("doc.items_table", "ru") == "Таблица позиций"
    assert catalog.label("unknown.code", "ru") == "unknown.code"
    assert set(catalog.required_blocks("invoice")) == {"doc.items_table", "doc.totals", "doc.payment_requisites"}
    assert catalog.blocks["doc.totals"].keep_with_previous


def test_sample_codes_exist_in_catalog() -> None:
    catalog = load_catalog()
    text = json.dumps([samples.contract(), samples.invoice(), samples.letter_short()], ensure_ascii=False)
    for code in {*samples.VALUES, "deal.number"}:
        assert code in catalog.variables, code
    assert '"doc.' in text
