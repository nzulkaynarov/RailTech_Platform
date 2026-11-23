"""Х-12: коды банков из файла ЦБ раз в месяц — добавляет новые, обновляет названия, ничего не удаляет; пропавшие
помечаются «нет в последнем файле ЦБ»; прогон идемпотентен; сбой скачивания пишется в журнал и не трогает справочник."""

import io
from unittest import mock

import httpx
import pytest
from openpyxl import Workbook
from rest_framework.test import APIClient

from crm.models import ActivityLog
from master_data import cbu_banks
from master_data.cbu_banks import BankFileError
from master_data.models import Bank
from master_data.tests.test_lookup_delete_and_archive import operator  # noqa: F401

BASE = "/api/v1/dictionaries"

# (код, признак, банк, филиал) — как в файле ЦБ: названия банков и филиалов на узбекском во всех листах.
ROWS = [
    ("00014", 1, "ASAKABANK", '"ASAKABANK" AJ BOSH OFISI'),
    ("00873", 1, "ANOR BANK", '"ANOR BANK" AKSIYADORLIK JAMIYATI'),
    ("00401", 3, "ALOQABANK", "TOSHKENT FILIALI"),
]
SHEETS = (
    ("O'zbekcha", "Filial kodi"),
    ("Ўзбекча", "Филиал коди"),
    ("Русский", "Код филиала"),
    ("English", "Branch code"),
)


def _xlsx(rows=ROWS) -> bytes:
    """Файл в раскладке ЦБ: четыре листа, шапка в восьмой строке, коды — текстом из пяти цифр."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, header in SHEETS:
        sheet = workbook.create_sheet(title)
        sheet.append(["Fayl yaratilgan sana"])
        sheet.append(["18.11.2024", "Filial belgisi"])
        for _ in range(5):
            sheet.append([None, None])
        sheet.append([header, "Filial belgisi", "Bank nomi", "Filial nomi"])
        for code, kind, bank, branch in rows:
            sheet.append([code, kind, bank, branch])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


@pytest.fixture
def small_file(monkeypatch):
    """Предохранитель «файл не короче N кодов» — для проверок пропавших кодов в малом файле."""
    monkeypatch.setattr(cbu_banks, "MIN_CODES", 2)


@pytest.mark.django_db
def test_adds_new_codes_keeps_old_and_updates_names(small_file):
    Bank.objects.create(code="99999", name="Старый банк вручную")  # руками, нет в файле
    Bank.objects.create(code="00014", name="Askabank")  # есть в файле, название устарело
    summary = cbu_banks.refresh_banks(_xlsx())

    assert (summary.added, summary.updated, summary.missing, summary.total) == (2, 1, 0, 3)
    assert Bank.objects.get(code="00014").name == '"ASAKABANK" AJ BOSH OFISI'
    new = Bank.objects.get(code="00873")
    assert (new.source, new.in_source, new.is_active) == ("cbu", True, True) and new.synced_at
    assert Bank.objects.get(code="00401").name == "ALOQABANK, TOSHKENT FILIALI"  # банка в названии филиала не видно
    kept = Bank.objects.get(code="99999")
    assert (kept.name, kept.source, kept.in_source) == ("Старый банк вручную", "", True)  # ручную строку не трогаем


@pytest.mark.django_db
def test_second_run_changes_nothing(small_file):
    cbu_banks.refresh_banks(_xlsx())
    before = list(Bank.objects.order_by("code").values("code", "name", "sort_order", "is_active", "in_source"))
    again = cbu_banks.refresh_banks(_xlsx())
    assert (again.added, again.updated, again.missing) == (0, 0, 0)
    assert list(Bank.objects.order_by("code").values("code", "name", "sort_order", "is_active", "in_source")) == before


@pytest.mark.django_db
def test_code_absent_from_the_latest_file_is_marked_not_deleted(small_file):
    cbu_banks.refresh_banks(_xlsx())
    seen = Bank.objects.get(code="00401").synced_at

    summary = cbu_banks.refresh_banks(_xlsx(ROWS[:2]))

    assert summary.missing == 1
    gone = Bank.objects.filter(code="00401").first()
    assert gone is not None, "a code missing from the file must stay in the directory"
    assert gone.in_source is False and gone.synced_at == seen  # дата — когда код последний раз был в файле

    cbu_banks.refresh_banks(_xlsx())  # вернулся в файл — снова «есть в источнике»
    assert Bank.objects.get(code="00401").in_source is True


@pytest.mark.django_db
def test_truncated_file_does_not_mark_anything_missing():
    cbu_banks.refresh_banks(_xlsx())  # 3 кода — меньше порога MIN_CODES
    cbu_banks.refresh_banks(_xlsx(ROWS[:1]))
    assert Bank.objects.filter(in_source=False).count() == 0


@pytest.mark.django_db
def test_name_changed_by_hand_is_kept(small_file, operator):  # noqa: F811
    cbu_banks.refresh_banks(_xlsx())
    api = APIClient()
    api.force_authenticate(user=operator)
    assert api.patch(f"{BASE}/banks/00014", {"name": {"ru": "Асака"}}, format="json").status_code == 200
    renamed = [("00014", 1, "ASAKABANK", "ASAKABANK YANGI NOM"), *ROWS[1:]]
    cbu_banks.refresh_banks(_xlsx(renamed))
    bank = Bank.objects.get(code="00014")
    assert (bank.name, bank.name_uz) == ("Асака", "ASAKABANK YANGI NOM")


@pytest.mark.django_db
def test_summary_goes_to_the_journal(small_file):
    cbu_banks.refresh_banks(_xlsx())
    entry = ActivityLog.objects.get(entity_type=cbu_banks.JOURNAL_ENTITY)
    assert entry.level == "INFO" and "добавлено 3" in entry.detail


@pytest.mark.django_db
def test_failed_download_is_logged_and_leaves_the_directory_alone(caplog):
    Bank.objects.create(code="00014", name="Askabank")
    with mock.patch.object(cbu_banks, "fetch_file", side_effect=BankFileError("ЦБ недоступен: ConnectTimeout")):
        with pytest.raises(BankFileError):
            cbu_banks.refresh_banks()
    assert list(Bank.objects.values_list("code", "name")) == [("00014", "Askabank")]
    entry = ActivityLog.objects.get(entity_type=cbu_banks.JOURNAL_ENTITY)
    assert entry.level == "WARNING" and "ConnectTimeout" in entry.detail
    assert "directory not updated" in caplog.text


@pytest.mark.django_db
def test_garbage_file_is_a_clear_error():
    with pytest.raises(BankFileError, match="xlsx"):
        cbu_banks.refresh_banks(b"PK not really a workbook")


def _client_returning(handler):
    real = httpx.Client
    return lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)


def test_file_link_is_taken_from_the_page_and_the_address_is_a_setting(settings):
    settings.CBU_BANKS_URL = "https://bank-list.example/branches/"
    asked = []

    def handler(request):
        asked.append(str(request.url))
        if request.url.path == "/branches/":
            return httpx.Response(200, text='<a href="/upload/x/Filiallar_haqida_malumot.xlsx">xlsx</a>')
        return httpx.Response(200, content=_xlsx())

    with mock.patch("httpx.Client", _client_returning(handler)):
        content = cbu_banks.fetch_file()
    assert asked == [
        "https://bank-list.example/branches/",
        "https://bank-list.example/upload/x/Filiallar_haqida_malumot.xlsx",
    ]
    assert len(cbu_banks.parse(content)) == 3


def test_page_without_a_file_link_and_unreachable_page_are_clear_errors(settings):
    settings.CBU_BANKS_URL = "https://bank-list.example/branches/"
    with mock.patch("httpx.Client", _client_returning(lambda request: httpx.Response(200, text="<html></html>"))):
        with pytest.raises(BankFileError, match="нет ссылки"):
            cbu_banks.fetch_file()

    def down(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    with mock.patch("httpx.Client", _client_returning(down)):
        with pytest.raises(BankFileError, match="недоступен"):
            cbu_banks.fetch_file()


@pytest.mark.django_db
def test_banks_show_the_source_and_refresh_queues_the_bank_job(small_file, operator):  # noqa: F811
    cbu_banks.refresh_banks(_xlsx())
    api = APIClient()
    api.force_authenticate(user=operator)
    kinds = {d["kind"]: d for d in api.get(BASE).json()["items"]}
    assert kinds["banks"]["source"]["name"]["ru"] == "ЦБ" and kinds["banks"]["source"]["synced_at"]
    rows = {r["code"]: r for r in api.get(f"{BASE}/banks", {"include_hidden": "true"}).json()["items"]}
    assert rows["00014"]["source"]["missing"] is False

    with (
        mock.patch("master_data.tasks.refresh_bank_codes.delay") as banks_job,
        mock.patch("master_data.tasks.refresh_exchange_rates.delay") as rates_job,
    ):
        assert api.post(f"{BASE}/banks/sync").status_code == 202
    banks_job.assert_called_once_with()
    rates_job.assert_not_called()


@pytest.mark.django_db
def test_monthly_job_is_scheduled_by_the_migration():
    from django_celery_beat.models import PeriodicTask

    job = PeriodicTask.objects.get(task="master_data.tasks.refresh_bank_codes")
    assert job.enabled and job.crontab.day_of_month == "1" and job.crontab.month_of_year == "*"
