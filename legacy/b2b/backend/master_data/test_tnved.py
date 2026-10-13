"""Синхронизация ТН ВЭД: пагинация, upsert, закрытие исчезнувших кодов, предохранитель."""

import datetime
import json

import pytest
from django.core.management import CommandError, call_command

from master_data import tnved
from master_data.models import HSCode

pytestmark = pytest.mark.django_db


def _row(code, name="Товар", unit="кг", extra="шт"):
    return [code, name, unit, extra]


@pytest.fixture
def small_floor(monkeypatch):
    """Тестам не нужны 10 тыс. строк — опускаем предохранитель до 3."""
    monkeypatch.setattr(tnved, "MIN_EXPECTED_CODES", 3)


def test_initial_sync_creates_codes_without_valid_from(small_floor):
    summary = tnved.sync_tnved_codes(
        rows=[
            _row("0101210000", "Лошади:чистопородные племенные животные"),
            _row("0101 29 100 0", "Лошади:прочие:убойные"),  # разделители вычищаются
            _row("8607191000", "Оси ж/д", "кг", ""),
        ]
    )
    assert summary["created"] == 3 and summary["closed"] == 0
    horse = HSCode.objects.get(code="0101291000")
    assert horse.level == 10
    assert horse.unit_name == "кг" and horse.extra_unit_name == "шт"
    assert horse.valid_from is None  # первичное наполнение — коды действовали и раньше
    assert horse.source == tnved.TNVED_SOURCE


def test_resync_updates_reopens_closes_and_stamps_valid_from(small_floor):
    tnved.sync_tnved_codes(rows=[_row("0101210000"), _row("0101291000"), _row("8607191000")])
    # промежуточный уровень из CSV-редакции — выгрузка tarif его закрывать не должна
    csv_heading = HSCode.objects.create(code="8607", name="Части подвижного состава", level=4)
    HSCode.objects.filter(code="8607191000").update(valid_until=datetime.date(2025, 1, 1))

    summary = tnved.sync_tnved_codes(
        rows=[
            _row("0101210000", "Лошади: новое наименование"),
            _row("8607191000"),  # вернулся в редакцию → открывается заново
            _row("9999999999"),  # новый код
        ]
    )
    assert summary["created"] == 1 and summary["closed"] == 1
    assert HSCode.objects.get(code="0101210000").name == "Лошади: новое наименование"
    assert HSCode.objects.get(code="8607191000").valid_until is None
    vanished = HSCode.objects.get(code="0101291000")
    assert vanished.valid_until == datetime.date.today()  # закрыт, не удалён
    assert HSCode.objects.get(code="9999999999").valid_from == datetime.date.today()
    csv_heading.refresh_from_db()
    assert csv_heading.valid_until is None  # уровень 4 не тронут
    # иерархия: 10-значный получил родителя-позицию
    assert HSCode.objects.get(code="8607191000").parent_id == csv_heading.pk


def test_sync_is_idempotent(small_floor):
    rows = [_row("0101210000"), _row("0101291000"), _row("8607191000")]
    tnved.sync_tnved_codes(rows=rows)
    summary = tnved.sync_tnved_codes(rows=rows)
    assert summary["created"] == 0 and summary["updated"] == 0 and summary["closed"] == 0


def test_truncated_response_aborts_without_touching_db(small_floor):
    tnved.sync_tnved_codes(rows=[_row("0101210000"), _row("0101291000"), _row("8607191000")])
    with pytest.raises(ValueError):
        tnved.sync_tnved_codes(rows=[_row("0101210000")])
    assert HSCode.objects.filter(valid_until__isnull=True).count() == 3  # ничего не закрыто


def test_bad_rows_are_skipped(small_floor):
    summary = tnved.sync_tnved_codes(
        rows=[
            _row("0101210000"),
            _row("0101291000"),
            _row("8607191000"),
            _row("", "Без кода"),
            _row("123", "Нечётная длина"),
            ["8607999000", ""],  # без наименования
        ]
    )
    assert summary["skipped"] == 3 and summary["fetched"] == 3


class _FakePagedClient:
    """Изображает httpx.Client поверх server-side DataTables пагинации."""

    def __init__(self, rows, page_size):
        self.rows = rows
        self.page_size = page_size
        self.requests = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, data=None):
        self.requests += 1
        start, end = data["iDisplayStart"], data["iDisplayStart"] + data["iDisplayLength"]
        page = self.rows[start:end]
        payload = {"iTotalRecords": len(self.rows), "aaData": page}

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return _Resp()


def test_fetch_paginates_to_the_end(monkeypatch):
    rows = [_row(f"{n:010d}") for n in range(25)]
    fake = _FakePagedClient(rows, page_size=10)
    monkeypatch.setattr("httpx.Client", lambda timeout, verify=None: fake)

    fetched = tnved.fetch_tnved_rows(page_size=10)
    assert len(fetched) == 25
    assert fake.requests == 3  # 10 + 10 + 5


def test_sync_command_loads_saved_response(small_floor, tmp_path):
    dump = tmp_path / "dump.json"
    dump.write_text(
        json.dumps({"aaData": [_row("0101210000"), _row("0101291000"), _row("8607191000")]}),
        encoding="utf-8",
    )
    call_command("sync_tnved", from_file=str(dump))
    assert HSCode.objects.count() == 3

    broken = tmp_path / "broken.json"
    broken.write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("sync_tnved", from_file=str(broken))
