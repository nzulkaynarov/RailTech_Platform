"""ПК-1: рамка договора берёт название и стороны у шаблона, а не зашивает «поставку»."""

from types import SimpleNamespace

import pytest
from django.utils import translation

from crm.services.documents.contract_frame import frame_of


def tpl(name, subject="", kind=""):
    return SimpleNamespace(name=name, subject=subject, counterparty_kind=kind)


@pytest.fixture(autouse=True)
def ru():
    with translation.override("ru"):
        yield


def test_supply_template_keeps_the_supply_frame_under_its_own_name():
    frame = frame_of(tpl("Договор поставки с клиентом", "supply", "client"))
    assert (frame.title, frame.first_party, frame.second_party, frame.supply) == (
        "Договор поставки с клиентом",
        "Поставщик",
        "Покупатель",
        True,
    )


def test_no_template_is_the_old_supply_path():
    assert frame_of(None).title == "Договор поставки"


@pytest.mark.parametrize(
    ("name", "kind", "second"),
    [("Договор о партнёрстве", "partner", "Партнёр"), ("Соглашение о неразглашении", "partner", "Партнёр")],
)
def test_base_documents_are_titled_and_split_by_the_template(name, kind, second):
    frame = frame_of(tpl(name, "", kind))
    assert frame.title == name
    assert (frame.first_party, frame.second_party) == ("Компания", second)
    assert frame.supply is False
    assert "Поставщик" not in (frame.first_party, frame.second_party, frame.first_sign, frame.second_sign)
    assert "Покупател" not in frame.second_sign


def test_without_counterparty_the_sides_are_neutral():
    frame = frame_of(tpl("Оферта", "", ""))
    assert (frame.first_party, frame.second_party) == ("Сторона 1", "Сторона 2")
